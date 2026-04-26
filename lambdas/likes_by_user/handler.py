"""
GET /likes/by-user - Friend-scoped paginated read of saved tracks.

Query string:
    email        - caller email (resolved via authorizer context fallback)
    targetEmail  - the user whose likes to fetch
    limit        - page size, default 50, max 200
    offset       - skip N items, default 0

Authorization:
- Self-access (caller == targetEmail) is always allowed.
- Otherwise, caller must have an *accepted* friendship with the target.
- Even when the friendship gate passes, the target's ``likes_public``
  flag must be true. If the target has flipped it off, we 403.

Response:
    {
        \"tracks\": [...],   # newest-first
        \"total\":  N,
        \"hasMore\": bool,
        \"likesPublic\": bool   # echoed for the iOS settings sync
    }
"""

from __future__ import annotations

from lambdas.common.errors import (
    AuthorizationError,
    ValidationError,
    handle_errors,
)
from lambdas.common.friendships_dynamo import are_users_friends
from lambdas.common.logger import get_logger
from lambdas.common.user_likes_dynamo import (
    MAX_LIKES_PAGE,
    get_likes_settings,
    query_user_likes,
)
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    require_fields,
    success_response,
)

log = get_logger(__file__)

HANDLER = "likes_by_user"

DEFAULT_LIMIT = 50
MAX_LIMIT = MAX_LIKES_PAGE  # 200 — matches the push cap


def _parse_int(raw, field: str, default: int, *, minimum: int, maximum: int | None) -> int:
    """Parse an integer query-param with bounds checks."""
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValidationError(
            message=f"{field} must be an integer",
            handler=HANDLER,
            function="handler",
            field=field,
        )
    if value < minimum:
        raise ValidationError(
            message=f"{field} must be >= {minimum}",
            handler=HANDLER,
            function="handler",
            field=field,
        )
    if maximum is not None and value > maximum:
        raise ValidationError(
            message=f"{field} cannot exceed {maximum}",
            handler=HANDLER,
            function="handler",
            field=field,
        )
    return value


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, "targetEmail")

    target_email = params.get("targetEmail")
    caller_email = get_caller_email(event)

    limit = _parse_int(
        params.get("limit"), "limit", DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT
    )
    offset = _parse_int(
        params.get("offset"), "offset", 0, minimum=0, maximum=None
    )

    is_self = caller_email == target_email

    # Visibility gate. We always read the target's likes settings because we
    # need ``likes_public`` for the privacy check AND we want to echo it
    # back to the client (so the iOS settings toggle stays in sync without
    # a second round-trip).
    settings = get_likes_settings(target_email)
    likes_public = bool(settings.get("likes_public", True))

    if not is_self:
        # Friend gate first — non-friends never even hit the privacy check
        # (avoids leaking that a private user exists by way of a 403 vs 404).
        if not are_users_friends(caller_email, target_email):
            log.warning(
                f"likes_by_user: non-friend access blocked "
                f"caller={caller_email} target={target_email}"
            )
            raise AuthorizationError(
                message="Not authorized to view this user's likes",
                handler=HANDLER,
                function="handler",
            )
        if not likes_public:
            log.info(
                f"likes_by_user: privacy gate blocked "
                f"caller={caller_email} target={target_email}"
            )
            raise AuthorizationError(
                message="Target user has hidden their likes",
                handler=HANDLER,
                function="handler",
            )

    log.info(
        f"likes_by_user: caller={caller_email} target={target_email} "
        f"limit={limit} offset={offset} self={is_self}"
    )

    page = query_user_likes(target_email, limit=limit, offset=offset)

    return success_response(
        {
            "tracks": page.get("tracks", []),
            "total": page.get("total", 0),
            "hasMore": bool(page.get("hasMore", False)),
            "likesPublic": likes_public,
        }
    )
