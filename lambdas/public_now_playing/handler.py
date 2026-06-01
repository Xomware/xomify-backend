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
    5. If nothing is actively playing, fall back to the user's most
       recently-played track via `GET /me/player/recently-played?limit=1`
       (requires the `user-read-recently-played` scope). Tokens that predate
       that scope return 403 insufficient-scope; we treat that specifically as
       "no data" (source="none"), NOT an error, so the endpoint keeps working
       for un-reauthorized users.

Unlike top-items/wrapped there is NO caching here: now-playing is real-time and
the frontend polls it. To keep the poller stable, ANY failure (token refresh,
Spotify error/timeout, 204 no-device, non-track item, recently-played failure,
insufficient scope) degrades to a 200 with source="none" and null fields —
never a 5xx. Only the public-gate 404s and the missing-userId 400 are non-200.

Return shape (frontend contract — pinned):
    { "isPlaying": bool,
      "track": { "name", "artist", "albumArt", "url" } | null,
      "progressMs": int | null,
      "durationMs": int | null,
      "source": "playing" | "recent" | "none",
      "playedAt": str | null }   # ISO timestamp, set only when source="recent"

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
from lambdas.common.spotify import Spotify, SpotifyInsufficientScopeError
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


def _none_source() -> dict:
    """The graceful "no data" contract (204/empty/error/insufficient scope)."""
    return {
        "isPlaying": False,
        "track": None,
        "progressMs": None,
        "durationMs": None,
        "source": "none",
        "playedAt": None,
    }


def _is_actively_playing(state: Optional[dict]) -> bool:
    """True only when there is a present, playing state carrying a track item."""
    if not state or not state.get("is_playing"):
        return False
    return isinstance(state.get("item"), dict)


def _map_playing(state: dict) -> dict:
    """
    Map an actively-playing `/me/player` state to the source="playing" contract.

    Caller guarantees `_is_actively_playing(state)` is True, so `item` is a
    dict. `_flatten_track` is defensive about missing album/artists/external_urls
    so a non-track item (podcast episode) degrades to {name, "", None, url}
    instead of raising.
    """
    item = state["item"]
    return {
        "isPlaying": True,
        "track": _flatten_track(item),
        "progressMs": state.get("progress_ms"),
        "durationMs": item.get("duration_ms"),
        "source": "playing",
        "playedAt": None,
    }


def _map_recent(recently_played: Optional[dict]) -> dict:
    """
    Map a `/me/player/recently-played` payload to the source="recent" contract.

    Reads `items[0]`; if its `track` is a dict we map it via `_flatten_track`
    and stamp `playedAt` from `items[0].played_at`. Empty/missing items, or an
    item with no resolvable track, degrade to source="none".
    """
    items = (recently_played or {}).get("items") or []
    if not items:
        return _none_source()

    first = items[0] or {}
    track = first.get("track")
    if not isinstance(track, dict):
        return _none_source()

    return {
        "isPlaying": False,
        "track": _flatten_track(track),
        "progressMs": None,
        "durationMs": None,
        "source": "recent",
        "playedAt": first.get("played_at"),
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
    # (token refresh, Spotify error/timeout) degrades to source="none" 200 so
    # the polling frontend never sees a 5xx.
    try:
        spotify = Spotify(user)
        state = spotify.get_playback_state()
    except Exception as err:  # noqa: BLE001 - real-time path must never 5xx
        log.warning(
            f"public_now_playing playback fetch failed userId={user_id} err={err} "
            f"-> source=none 200"
        )
        return success_response(_none_source())

    # 4a. Actively playing a track -> source="playing".
    if _is_actively_playing(state):
        body = _map_playing(state)
        log.info(
            f"public_now_playing userId={user_id} source=playing "
            f"hasTrack={body['track'] is not None}"
        )
        return success_response(body)

    # 4b. Nothing actively playing -> fall back to recently-played. A 403
    # insufficient-scope (token predates the `user-read-recently-played` scope)
    # is treated as "no data", NOT an error, so the endpoint keeps working for
    # users who have not re-authorized yet. Any other failure also degrades.
    try:
        recently_played = spotify.get_recently_played(limit=1)
    except SpotifyInsufficientScopeError as err:
        log.warning(
            f"public_now_playing recently-played insufficient scope userId={user_id} "
            f"err={err} -> source=none 200 (user likely needs to re-authorize for "
            f"user-read-recently-played)"
        )
        return success_response(_none_source())
    except Exception as err:  # noqa: BLE001 - real-time path must never 5xx
        log.warning(
            f"public_now_playing recently-played fetch failed userId={user_id} "
            f"err={err} -> source=none 200"
        )
        return success_response(_none_source())

    body = _map_recent(recently_played)
    log.info(
        f"public_now_playing userId={user_id} source={body['source']} "
        f"hasTrack={body['track'] is not None} playedAt={body['playedAt']}"
    )
    return success_response(body)
