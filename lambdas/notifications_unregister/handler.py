"""
POST /notifications/unregister - Remove an APNs device token for the caller.

Caller identity (`email`) is sourced from the JWT-authorizer context via
`get_caller_email`. The body only carries the target device token to remove.

Body:
    {
        "deviceToken": "<hex>"
    }
"""

from __future__ import annotations

from typing import Any

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    require_fields,
    success_response,
)
from lambdas.common.device_tokens_dynamo import delete_token

log = get_logger(__file__)

HANDLER = "notifications_unregister"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    body = parse_body(event)
    require_fields(body, "deviceToken")

    email = get_caller_email(event)
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
