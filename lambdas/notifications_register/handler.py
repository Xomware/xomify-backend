"""
POST /notifications/register - Store/refresh an APNs device token for a user.

Body:
    {
        "email": "user@...",
        "deviceToken": "<hex>",
        "digestEnabled": true,               # optional, default true
        "queueNotificationsEnabled": true    # optional, default true
    }
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.device_tokens_dynamo import upsert_token

log = get_logger(__file__)

HANDLER = "notifications_register"


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "email", "deviceToken")

    email = body.get("email")
    device_token = body.get("deviceToken")

    if not isinstance(device_token, str) or len(device_token) < 8:
        raise ValidationError(
            message="deviceToken must be a non-empty string",
            handler=HANDLER,
            function="handler",
            field="deviceToken",
        )

    digest_enabled = _as_bool(body.get("digestEnabled"), True)
    queue_notifications_enabled = _as_bool(body.get("queueNotificationsEnabled"), True)

    log.info(
        f"Registering device token for {email} "
        f"(digestEnabled={digest_enabled}, queueEnabled={queue_notifications_enabled})"
    )

    upsert_token(
        email=email,
        device_token=device_token,
        digest_enabled=digest_enabled,
        queue_notifications_enabled=queue_notifications_enabled,
    )

    return success_response({
        "ok": True,
        "email": email,
        "digestEnabled": digest_enabled,
        "queueNotificationsEnabled": queue_notifications_enabled,
    })
