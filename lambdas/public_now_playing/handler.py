"""
GET /music/public-now-playing?userId=<id> - Public, UNAUTHENTICATED endpoint.

Serves a single allowlisted user's CURRENT playback so an anonymous frontend
(xomware.com `/music` hub) can render a live "now playing" widget that polls.

Mirrors `public_top_items` / `public_wrapped` for the gate/resolve scaffolding:
    1. No authorizer — identity from a `userId` query param, NOT a JWT.
    2. userId -> user record: `get_user_by_user_id` (filtered scan for v1).
    3. Public gate — shared allowlist in `lambdas/common/public_access.py`
       (default-deny). Allowlist miss / unknown userId both -> 404.
    4. Build a sync `Spotify(user)` client (token refresh) and call
       `GET /me/player` (Get Playback State). This works with the EXISTING
       `user-read-playback-state` scope the user already granted — we do NOT
       use `/me/player/currently-playing` (needs a scope we lack).

Unlike top-items/wrapped there is NO caching here: now-playing is real-time and
the frontend polls it. To keep the poller stable, ANY failure (token refresh,
Spotify error/timeout, 204 no-device, non-track item) degrades to a 200 with
`{ isPlaying: false, track: null, progressMs: null, durationMs: null }` — never
a 5xx. Only the public-gate 404s and the missing-userId 400 are non-200.

Return shape (frontend contract — pinned):
    { "isPlaying": bool,
      "track": { "name", "artist", "albumArt", "url" } | null,
      "progressMs": int | null,
      "durationMs": int | null }

INFRA NOTE (handled separately in xomify-infrastructure, not here): this lambda
folder is `public_now_playing`, so the function must be named
`xomify-public-now-playing` (folder-based convention). The route needs wiring
as `GET /music/public-now-playing` with `authorization = "NONE"`.
"""

from typing import Any, Optional

from lambdas.common.dynamo_helpers import get_user_by_user_id
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.public_access import PUBLIC_USER_IDS as _DEFAULT_PUBLIC_USER_IDS
from lambdas.common.public_access import is_public
from lambdas.common.spotify import Spotify
from lambdas.common.top_items_transform import _flatten_track
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "public_now_playing"

# Module-level allowlist bound from the shared source of truth. Tests patch this
# name; `_is_public` reads through it — identical pattern to public_top_items.
PUBLIC_USER_IDS = _DEFAULT_PUBLIC_USER_IDS


def _is_public(user_id: str) -> bool:
    """Default-deny gate: only allowlisted userIds are public."""
    return is_public(user_id, PUBLIC_USER_IDS)


def _not_playing() -> dict:
    """The graceful "nothing playing" contract (used for 204, empty, errors)."""
    return {
        "isPlaying": False,
        "track": None,
        "progressMs": None,
        "durationMs": None,
    }


def _map_playback(state: Optional[dict]) -> dict:
    """
    Map a Spotify `/me/player` playback-state object to the frontend contract.

    `state` is None (204/empty) -> not playing. A present state may still carry
    a non-track `item` (e.g. a podcast episode, `currently_playing_type !=
    "track"`); we guard for missing `album`/`artists` via `_flatten_track`'s
    defensive `.get()` chain and degrade to a best-effort name with null
    albumArt rather than 500.
    """
    if not state:
        return _not_playing()

    item = state.get("item")
    if not isinstance(item, dict):
        # Active device but no resolvable item (e.g. ad, or item not exposed).
        return {
            "isPlaying": bool(state.get("is_playing")),
            "track": None,
            "progressMs": state.get("progress_ms"),
            "durationMs": None,
        }

    # `_flatten_track` is defensive about missing album/artists/external_urls,
    # so a non-track item (podcast episode) degrades to {name, "", None, url}
    # instead of raising.
    track = _flatten_track(item)

    return {
        "isPlaying": bool(state.get("is_playing")),
        "track": track,
        "progressMs": state.get("progress_ms"),
        "durationMs": item.get("duration_ms"),
    }


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    query = get_query_params(event)
    user_id = (query.get("userId") or "").strip()

    # 1. Validate presence of userId.
    if not user_id:
        raise ValidationError(
            message="Missing required query parameter: userId",
            handler=HANDLER,
            function="handler",
            field="userId",
        )

    # 2 & 3. Resolve + gate. Both "unknown user" and "not public" collapse to
    # 404 so callers cannot enumerate which userIds exist or are public.
    user = get_user_by_user_id(user_id)
    if user is None or not _is_public(user_id):
        log.info(
            f"public_now_playing denied userId={user_id} "
            f"reason={'unknown' if user is None else 'not_public'}"
        )
        raise NotFoundError(
            message="Not found",
            handler=HANDLER,
            function="handler",
        )

    email = user.get("email")
    if not email:
        # Allowlisted user record with no email is a data integrity problem;
        # treat as not-found rather than leaking a 5xx to the public.
        log.warning(f"public_now_playing allowlisted user missing email userId={user_id}")
        raise NotFoundError(
            message="Not found",
            handler=HANDLER,
            function="handler",
        )

    # 4. Build a sync Spotify client + fetch current playback. ANY failure
    # (token refresh, Spotify error/timeout) degrades to not-playing 200 so the
    # polling frontend never sees a 5xx.
    try:
        spotify = Spotify(user)
        state = spotify.get_playback_state()
    except Exception as err:  # noqa: BLE001 - real-time path must never 5xx
        log.warning(
            f"public_now_playing fetch failed userId={user_id} err={err} -> not playing 200"
        )
        return success_response(_not_playing())

    body = _map_playback(state)
    log.info(
        f"public_now_playing userId={user_id} isPlaying={body['isPlaying']} "
        f"hasTrack={body['track'] is not None}"
    )
    return success_response(body)
