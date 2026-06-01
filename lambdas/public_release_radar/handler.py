"""
GET /music/public-release-radar?userId=<id> - Public, UNAUTHENTICATED endpoint.

Serves a single allowlisted user's most recent weekly Release Radar snapshot so
an anonymous frontend (xomware.com `/music` hub) can render Dom's new releases.
Implements GitHub issue #187.

Mirrors `public_top_items` exactly:
    1. No authorizer — identity comes from a `userId` query param, NOT a JWT.
    2. userId -> user record (the users table is keyed by email):
       `get_user_by_user_id` (filtered scan for v1).
    3. Public gate — the shared hardcoded allowlist in
       `lambdas/common/public_access.py` (default-deny). Allowlist miss and
       unknown userId both return 404 to avoid enumeration.
    4. Read-with-fallback — read the LATEST stored weekly radar snapshot from
       the release-radar history table (`get_user_release_radar_history`,
       limit=1). This is cache-first: the weekly cron already pulled and stored
       the releases, so we never trigger a fresh Spotify pull here.
    5. Flatten transform -> the flat `RadarProfile` frontend contract.

Resilience: on any read failure or no-data, this returns 200 with an empty
`releases` array + `updatedAt: null`, NOT a 5xx, so the page degrades
gracefully (same rule as public_top_items).

INFRA NOTE (handled separately in xomify-infrastructure, not here): this lambda
folder is `public_release_radar`, so the function must be named
`xomify-public-release-radar` (folder-based convention). The route needs wiring
under the `music` service prefix with `authorization = "NONE"`.
"""

from typing import Any

from lambdas.common.dynamo_helpers import get_user_by_user_id
from lambdas.common.errors import handle_errors, NotFoundError, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.public_access import PUBLIC_USER_IDS as _DEFAULT_PUBLIC_USER_IDS
from lambdas.common.public_access import is_public
from lambdas.common.release_radar_dynamo import get_user_release_radar_history
from lambdas.common.release_radar_transform import flatten_public_release_radar
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "public_release_radar"

# Module-level allowlist bound from the shared source of truth. Tests patch this
# name (`patch.object(handler, "PUBLIC_USER_IDS", ...)`), so `_is_public` reads
# through it — identical pattern to public_top_items.
PUBLIC_USER_IDS = _DEFAULT_PUBLIC_USER_IDS


def _is_public(user_id: str) -> bool:
    """Default-deny gate: only allowlisted userIds are public."""
    return is_public(user_id, PUBLIC_USER_IDS)


def _empty_public_response() -> dict:
    """Flat contract with empty releases + null updatedAt (graceful degradation)."""
    return flatten_public_release_radar(None)


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
            f"public_release_radar denied userId={user_id} "
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
        log.warning(
            f"public_release_radar allowlisted user missing email userId={user_id}"
        )
        raise NotFoundError(
            message="Not found",
            handler=HANDLER,
            function="handler",
        )

    # 4. Read the latest stored weekly snapshot (cache-first; no Spotify call).
    # On any read failure, degrade to an empty 200 rather than a 5xx.
    try:
        weeks = get_user_release_radar_history(email, limit=1)
    except Exception as err:  # noqa: BLE001 - read failure must not 500 the public page
        log.warning(
            f"public_release_radar read failed userId={user_id} err={err} -> empty 200"
        )
        return success_response(_empty_public_response())

    if not weeks:
        log.info(f"public_release_radar no_data userId={user_id} -> empty 200")
        return success_response(_empty_public_response())

    # 5. Flatten the most recent week (history is returned newest-first).
    log.info(f"public_release_radar hit userId={user_id} weekKey={weeks[0].get('weekKey')}")
    body = flatten_public_release_radar(weeks[0])
    return success_response(body)
