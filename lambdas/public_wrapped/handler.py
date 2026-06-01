"""
GET /music/public-wrapped?userId=<id> - Public, UNAUTHENTICATED endpoint.

Serves a single allowlisted user's monthly Wrapped archive so an anonymous
frontend (xomware.com `/music` hub) can render Dom's monthly top tracks /
artists / genres. Implements GitHub issue #188.

Mirrors `public_top_items` for the gate/resolve/resilience scaffolding, but is
heavier because the stored `MonthlyWrap` rows hold BARE Spotify IDs, not
hydrated objects:

    Stored shape (per month, from the wrapped cron):
        { monthKey, topSongIds{short/medium/long_term:[ids]},
          topArtistIds{...}, topGenres{...:{genre:count}}, playlistId, createdAt }

Flow:
    1. No authorizer — identity from `userId` query param, NOT a JWT.
    2. userId -> user record: `get_user_by_user_id`.
    3. Public gate — shared allowlist in `lambdas/common/public_access.py`
       (default-deny). Allowlist miss / unknown userId both -> 404.
    4. Read all stored wraps (`get_user_wrap_history`, newest first).
    5. HYDRATION: for each month take the `short_term` top-5 song + artist IDs
       and hydrate them to full objects via Spotify's BATCH endpoints
       (`GET /v1/tracks?ids=`, `GET /v1/artists?ids=`) using the user's stored
       refresh token (a single sync Spotify client, reused across all months).
       Genres are already counts -> sorted desc, top 5 by the shared
       `_flatten_genres` helper.
    6. Flatten -> the `WrappedArchive` contract (newest month first).

Resilience: on any read/hydration failure or no-data, return 200 with
`months: []` + `updatedAt: null`, NOT a 5xx (same rule as public_top_items).
A single month that fails to hydrate is skipped rather than failing the whole
archive.

INFRA NOTE (handled separately in xomify-infrastructure, not here): this lambda
folder is `public_wrapped`, so the function must be named `xomify-public-wrapped`
(folder-based convention). The route needs wiring under the `music` service
prefix with `authorization = "NONE"`.
"""

from typing import Any, Optional

from lambdas.common.dynamo_helpers import get_user_by_user_id, get_user_wrap_history
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.public_access import PUBLIC_USER_IDS as _DEFAULT_PUBLIC_USER_IDS
from lambdas.common.public_access import is_public
from lambdas.common.spotify import Spotify
from lambdas.common.utility_helpers import get_query_params, success_response
from lambdas.common.wrapped_transform import flatten_public_wrapped, flatten_wrapped_month

log = get_logger(__file__)

HANDLER = "public_wrapped"

# Hydrate only the short_term top 5 (matches the public top-items window and
# keeps Spotify batch calls tiny).
_HYDRATE_RANGE = "short_term"
_MAX_ITEMS = 5

# Module-level allowlist bound from the shared source of truth. Tests patch this
# name; `_is_public` reads through it — identical pattern to public_top_items.
PUBLIC_USER_IDS = _DEFAULT_PUBLIC_USER_IDS


def _is_public(user_id: str) -> bool:
    """Default-deny gate: only allowlisted userIds are public."""
    return is_public(user_id, PUBLIC_USER_IDS)


def _empty_public_response() -> dict:
    """Flat contract with empty months + null updatedAt (graceful degradation)."""
    return flatten_public_wrapped(None, None)


def _short_term_top(ids_by_range: Optional[dict]) -> list:
    """Pull the short_term list and slice to the top `_MAX_ITEMS` ids."""
    ids = (ids_by_range or {}).get(_HYDRATE_RANGE) or []
    return list(ids)[:_MAX_ITEMS]


def _hydrate_month(spotify: Spotify, wrap: dict) -> Optional[dict]:
    """
    Hydrate one stored wrap into a flattened month entry.

    Reads `topSongIds`/`topArtistIds` (short_term, top 5), hydrates them via the
    Spotify batch endpoints, and maps everything into the frontend month shape.
    Returns None if this month fails to hydrate (caller skips it) so one bad
    month never sinks the whole archive.
    """
    month_key = wrap.get("monthKey")
    try:
        song_ids = _short_term_top(wrap.get("topSongIds"))
        artist_ids = _short_term_top(wrap.get("topArtistIds"))

        tracks = spotify.get_tracks_by_ids(song_ids) if song_ids else []
        artists = spotify.get_artists_by_ids(artist_ids) if artist_ids else []

        # Genres are stored per-range as {genre: count}; reuse short_term.
        genres = (wrap.get("topGenres") or {}).get(_HYDRATE_RANGE) or {}

        return flatten_wrapped_month(
            month_key=month_key,
            tracks=tracks,
            artists=artists,
            genres=genres,
            playlist_id=wrap.get("playlistId"),
        )
    except Exception as err:  # noqa: BLE001 - skip a bad month, never 500 the page
        log.warning(f"public_wrapped month hydrate failed monthKey={month_key} err={err}")
        return None


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
            f"public_wrapped denied userId={user_id} "
            f"reason={'unknown' if user is None else 'not_public'}"
        )
        raise NotFoundError(
            message="Not found",
            handler=HANDLER,
            function="handler",
        )

    email = user.get("email")
    if not email:
        log.warning(f"public_wrapped allowlisted user missing email userId={user_id}")
        raise NotFoundError(
            message="Not found",
            handler=HANDLER,
            function="handler",
        )

    # 4. Read all stored wraps (newest first). Read failure -> empty 200.
    try:
        wraps = get_user_wrap_history(email, ascending=False)
    except Exception as err:  # noqa: BLE001 - read failure must not 500 the public page
        log.warning(f"public_wrapped read failed userId={user_id} err={err} -> empty 200")
        return success_response(_empty_public_response())

    if not wraps:
        log.info(f"public_wrapped no_data userId={user_id} -> empty 200")
        return success_response(_empty_public_response())

    # 5. Hydrate each month via a single reused Spotify client. Building the
    # client (token refresh) failing must degrade to empty, never 5xx.
    try:
        spotify = Spotify(user)
    except Exception as err:  # noqa: BLE001 - auth/token failure -> graceful empty
        log.warning(f"public_wrapped spotify init failed userId={user_id} err={err} -> empty 200")
        return success_response(_empty_public_response())

    months = []
    for wrap in wraps:
        month = _hydrate_month(spotify, wrap)
        if month is not None:
            months.append(month)

    if not months:
        log.info(f"public_wrapped all months failed hydration userId={user_id} -> empty 200")
        return success_response(_empty_public_response())

    # updatedAt = newest month's createdAt (wraps are newest-first).
    updated_at = wraps[0].get("createdAt")
    log.info(f"public_wrapped hit userId={user_id} months={len(months)}")
    body = flatten_public_wrapped(months, updated_at)
    return success_response(body)
