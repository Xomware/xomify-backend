"""
GET /music/public-top-items?userId=<id> - Public, UNAUTHENTICATED endpoint.

Serves a single allowlisted user's cached top tracks/artists/genres (short_term
only) so an anonymous frontend (xomware.com) can render Dom's listening stats.

Differences from the auth-gated `/user/top-items`:
    1. No authorizer — the route is wired `authorization = "NONE"` (see infra
       note below). Identity comes from a `userId` query param, NOT a JWT.
    2. userId -> user record resolution (the users table + cache are keyed by
       email): `get_user_by_user_id` (filtered scan for v1).
    3. Public gate — a hardcoded allowlist (default-deny). Allowlist miss and
       unknown userId both return 404 to avoid enumeration.
    4. Flatten + slice transform — collapse the range-keyed cache shape to the
       flat top-5 short_term-only frontend contract.

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
import os
from typing import Any, Optional

from lambdas.common.dynamo_helpers import get_user_by_user_id
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.top_items_cache import get_cached_with_meta, set_cached
from lambdas.common.top_items_fetch import _fetch_top_items_with_partial_tolerance
from lambdas.common.top_items_transform import PUBLIC_RANGE, flatten_public_top_items
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "public_top_items"


# ============================================
# Public visibility gate (v1: hardcoded allowlist)
# ============================================
# v1 gate is a hardcoded allowlist of public Spotify userIds. Default-deny —
# any userId not in this set returns 404 (same as unknown user) to avoid
# enumeration. v1 contains only Dom's userId.
#
# TODO(dom): replace "PLACEHOLDER_DOM_USER_ID" with Dom's real Spotify userId.
#
# v2 upgrade path: replace this constant with a data-driven `profileVisibility`
# flag on the users table. The gate check below (`_is_public`) is the only thing
# that changes — the rest of the handler is agnostic to how "public" is decided.
#
# Optionally overridable via the `PUBLIC_USER_IDS` env var (comma-separated) so
# infra can inject the real id without a code change.
def _load_public_user_ids() -> frozenset[str]:
    raw = os.environ.get("PUBLIC_USER_IDS", "")
    env_ids = {uid.strip() for uid in raw.split(",") if uid.strip()}
    if env_ids:
        return frozenset(env_ids)
    return frozenset({"PLACEHOLDER_DOM_USER_ID"})


PUBLIC_USER_IDS = _load_public_user_ids()


def _is_public(user_id: str) -> bool:
    """Default-deny gate: only allowlisted userIds are public."""
    return user_id in PUBLIC_USER_IDS


def _empty_public_response() -> dict:
    """Flat contract with empty arrays + null updatedAt (graceful degradation)."""
    return flatten_public_top_items(None, None)


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

    # 4. Cache hit -> transform + return (no Spotify call).
    cached = get_cached_with_meta(email)
    if cached is not None:
        log.info(f"public_top_items cache=hit userId={user_id}")
        body = flatten_public_top_items(cached, cached.get("cachedAt"))
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

    # 6. If short_term itself failed (or is empty) and we have no data to serve,
    # return 200 with empty arrays + updatedAt=null rather than a 5xx so the
    # landing page stays stable.
    short_term_tracks = (payload.get("tracks") or {}).get(PUBLIC_RANGE)
    if PUBLIC_RANGE in failed_ranges or short_term_tracks is None:
        log.info(
            f"public_top_items short_term unavailable userId={user_id} "
            f"failed_ranges={failed_ranges} -> empty 200"
        )
        return success_response(_empty_public_response())

    # 7. Transform the freshly fetched payload. updatedAt is null here because
    # the live payload carries no cachedAt (the frontend treats null as "just
    # now / unknown" and renders gracefully).
    cached_at: Optional[str] = None
    body = flatten_public_top_items(payload, cached_at)
    return success_response(body)
