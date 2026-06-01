"""
GET /music/public-top-items?userId=<id>[&range=<short|medium|long>_term]
    - Public, UNAUTHENTICATED endpoint.

Serves a single allowlisted user's cached top tracks/artists/genres so an
anonymous frontend (xomware.com) can render Dom's listening stats. The cache
stores all three Spotify ranges (short_term/medium_term/long_term); the
optional `?range=` query param selects which one to flatten (default
short_term). An absent or invalid range clamps to short_term (logged, never a
400) so the time-range switcher on the frontend can never break the endpoint.

Differences from the auth-gated `/user/top-items`:
    1. No authorizer — the route is wired `authorization = "NONE"` (see infra
       note below). Identity comes from a `userId` query param, NOT a JWT.
    2. userId -> user record resolution (the users table + cache are keyed by
       email): `get_user_by_user_id` (filtered scan for v1).
    3. Public gate — a hardcoded allowlist (default-deny). Allowlist miss and
       unknown userId both return 404 to avoid enumeration.
    4. Flatten + slice transform — collapse the range-keyed cache shape to the
       flat top-5 frontend contract for the requested range.

All Spotify/cache logic is reused from existing modules — no duplication. The
handler is: resolve user -> gate -> reuse cache/fetch -> transform -> respond.

Resilience: on total failure (no cache, live fetch fails for short_term) this
returns 200 with empty arrays + `updatedAt: null`, NOT a 5xx, so the landing
page degrades gracefully rather than erroring.

INFRA NOTE (handled separately in xomify-infrastructure, not here): this route
needs wiring under a new `music` service prefix with `authorization = "NONE"`,
and `https://xomware.com` added to `cors_allowed_origins`. No infra is written
in this repo.
"""

import asyncio
from typing import Any, Optional

from lambdas.common.dynamo_helpers import get_user_by_user_id
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.public_access import PUBLIC_USER_IDS as _DEFAULT_PUBLIC_USER_IDS
from lambdas.common.public_access import is_public
from lambdas.common.top_items_cache import get_cached_with_meta, set_cached
from lambdas.common.top_items_fetch import _fetch_top_items_with_partial_tolerance
from lambdas.common.top_items_transform import (
    PUBLIC_RANGE,
    VALID_RANGES,
    flatten_public_top_items,
)
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "public_top_items"


# ============================================
# Public visibility gate (v1: hardcoded allowlist)
# ============================================
# The allowlist + gate now live in `lambdas/common/public_access.py` so all
# three public `/music/*` endpoints share one source of truth. We bind a
# module-level `PUBLIC_USER_IDS` here so existing tests can keep patching the
# constant on this module (`patch.object(handler, "PUBLIC_USER_IDS", ...)`) and
# `_is_public` reads through that patchable name.
PUBLIC_USER_IDS = _DEFAULT_PUBLIC_USER_IDS


def _is_public(user_id: str) -> bool:
    """Default-deny gate: only allowlisted userIds are public."""
    return is_public(user_id, PUBLIC_USER_IDS)


def _resolve_range(query: dict) -> str:
    """
    Resolve the requested time range from `?range=`, clamping to PUBLIC_RANGE.

    Never raises: an absent or invalid range falls back to short_term (logged)
    so a bad value from the frontend switcher degrades instead of 400-ing.
    """
    raw = (query.get("range") or "").strip()
    if raw in VALID_RANGES:
        return raw
    if raw:
        log.info(f"public_top_items invalid range='{raw}' -> defaulting to {PUBLIC_RANGE}")
    return PUBLIC_RANGE


def _empty_public_response(range_key: str = PUBLIC_RANGE) -> dict:
    """Flat contract with empty arrays + null updatedAt (graceful degradation)."""
    return flatten_public_top_items(None, None, range_key)


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    query = get_query_params(event)
    user_id = (query.get("userId") or "").strip()
    # Time range for the switcher. Invalid/absent clamps to short_term (logged).
    range_key = _resolve_range(query)

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
            f"public_top_items denied userId={user_id} "
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
        log.warning(f"public_top_items allowlisted user missing email userId={user_id}")
        raise NotFoundError(
            message="Not found",
            handler=HANDLER,
            function="handler",
        )

    # 4. Cache hit -> transform + return (no Spotify call). The cache holds all
    # three ranges, so a hit serves the requested range directly.
    cached = get_cached_with_meta(email)
    if cached is not None:
        log.info(f"public_top_items cache=hit userId={user_id} range={range_key}")
        body = flatten_public_top_items(cached, cached.get("cachedAt"), range_key)
        return success_response(body)

    # 5. Cache miss -> live fetch (last resort).
    log.info(f"public_top_items cache=miss userId={user_id} (live fetch)")
    payload, failed_ranges = asyncio.run(
        _fetch_top_items_with_partial_tolerance(user)
    )

    # Only write the cache on a fully successful fetch (same rule as
    # user_top_items: a partial response must not poison the cache).
    if not failed_ranges:
        try:
            set_cached(email, payload)
        except Exception as err:  # noqa: BLE001 - cache write failure must not 500
            log.warning(
                f"public_top_items cache write failed userId={user_id} err={err}"
            )

    # 6. If the REQUESTED range failed (or is empty) and we have no data to
    # serve, return 200 with empty arrays + updatedAt=null rather than a 5xx so
    # the landing page stays stable.
    requested_tracks = (payload.get("tracks") or {}).get(range_key)
    if range_key in failed_ranges or requested_tracks is None:
        log.info(
            f"public_top_items range={range_key} unavailable userId={user_id} "
            f"failed_ranges={failed_ranges} -> empty 200"
        )
        return success_response(_empty_public_response(range_key))

    # 7. Transform the freshly fetched payload. updatedAt is null here because
    # the live payload carries no cachedAt (the frontend treats null as "just
    # now / unknown" and renders gracefully).
    cached_at: Optional[str] = None
    body = flatten_public_top_items(payload, cached_at, range_key)
    return success_response(body)
