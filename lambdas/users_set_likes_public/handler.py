"""
POST /users/likes-public - Toggle the caller's "show my likes to friends" flag.

Body:
    { \"email\": \"<caller email>\", \"value\": <bool> }

Authorization:
- The body's ``email`` MUST equal the resolved caller email — users
  can only flip their own flag.

Returns:
    { \"email\": str, \"likesPublic\": bool }
"""

from __future__ import annotations

from lambdas.common.errors import (
    AuthorizationError,
    ValidationError,
    handle_errors,
)
from lambdas.common.logger import get_logger
from lambdas.common.user_likes_dynamo import set_likes_public
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    require_fields,
    success_response,
)

log = get_logger(__file__)

HANDLER = "users_set_likes_public"


def _coerce_bool(raw, field: str) -> bool:
    """Strict bool coercion. Accept the standard JSON literal or the
    common stringy ``"true"`` / ``"false"`` forms iOS may send.
    """
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValidationError(
        message=f"{field} must be a boolean",
        handler=HANDLER,
        function="handler",
        field=field,
    )


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "email", "value")

    body_email = body.get("email")
    caller_email = get_caller_email(event)

    if not isinstance(body_email, str) or body_email != caller_email:
        log.warning(
            f"Cross-user likes-public toggle rejected: "
            f"caller={caller_email} bodyEmail={body_email}"
        )
        raise AuthorizationError(
            message="Not authorized to update another user's settings",
            handler=HANDLER,
            function="handler",
        )

    value = _coerce_bool(body.get("value"), "value")

    log.info(f"Setting likes_public={value} for {caller_email}")
    persisted = set_likes_public(caller_email, value)

    return success_response({"email": caller_email, "likesPublic": persisted})
