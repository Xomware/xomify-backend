"""
POST /notifications/unregister - Remove an APNs device token for a user.

Body:
    {
        "email": "user@...",
        "deviceToken": "<hex>"
    }
"""

from __future__ import annotations

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.device_tokens_dynamo import delete_token

log = get_logger(__file__)

HANDLER = "notifications_unregister"


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, "email", "deviceToken")

    email = body.get("email")
    device_token = body.get("deviceToken")

    if not isinstance(device_token, str) or not device_token:
        raise ValidationError(
            message="deviceToken must be a non-empty string",
            handler=HANDLER,
            function="handler",
            field="deviceToken",
        )

    log.info(f"Unregistering device token for {email}")
    delete_token(email=email, device_token=device_token)

    return success_response({"ok": True, "email": email})
