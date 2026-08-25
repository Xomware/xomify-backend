"""
POST /notifications/register - Store/refresh an APNs device token for the caller.

Caller identity (`email`) is sourced from the JWT-authorizer context via
`get_caller_email`. The body only carries the target device token + optional
preference flags.

Body:
    {
        "deviceToken": "<hex>",

        # NEW — the full per-kind map. Only the flags present are written;
        # anything omitted keeps whatever the row already had (or the registry
        # default, if the row has never carried it).
        "preferences": { "shareReceivedEnabled": true, ... },

        # LEGACY — the two flags that existed before the registry. Still
        # honoured so an older client build keeps working; they fold into
        # `preferences`.
        "digestEnabled": true,
        "queueNotificationsEnabled": true
    }

Returns the EFFECTIVE preference map — every kind, defaults filled in — so a
Settings screen can render all sixteen toggles from one response rather than
having to know the defaults itself.
"""

from __future__ import annotations

from typing import Any, Optional

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    require_fields,
    success_response,
)
from lambdas.common.device_tokens_dynamo import upsert_token
from lambdas.common.notification_kinds import (
    effective_preferences,
    sanitize_preferences,
)

log = get_logger(__file__)

HANDLER = "notifications_register"


def _as_bool(value: Any, default: Optional[bool]) -> Optional[bool]:
    """
    None in, None out — the caller distinguishes "client said false" from
    "client did not mention this flag". Collapsing the two would make every
    registration write every flag, which is exactly what the sparse upsert
    exists to avoid.
    """
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    body = parse_body(event)
    require_fields(body, "deviceToken")

    email = get_caller_email(event)
    device_token = body.get("deviceToken")

    if not isinstance(device_token, str) or len(device_token) < 8:
        raise ValidationError(
            message="deviceToken must be a non-empty string",
            handler=HANDLER,
            function="handler",
            field="deviceToken",
        )

    preferences = sanitize_preferences(body.get("preferences") or {})

    # Legacy top-level flags, from client builds that predate the registry.
    digest_enabled = _as_bool(body.get("digestEnabled"), None)
    queue_notifications_enabled = _as_bool(body.get("queueNotificationsEnabled"), None)

    log.info(
        f"Registering device token for {email} "
        f"(explicit flags: {sorted(preferences)}, "
        f"legacy digest={digest_enabled}, legacy queue={queue_notifications_enabled})"
    )

    row = upsert_token(
        email=email,
        device_token=device_token,
        preferences=preferences,
        digest_enabled=digest_enabled,
        queue_notifications_enabled=queue_notifications_enabled,
    )

    effective = effective_preferences(row)

    return success_response({
        "ok": True,
        "email": email,
        "preferences": effective,
        # Kept at the top level for older clients that read them there.
        "digestEnabled": effective["digestEnabled"],
        "queueNotificationsEnabled": effective["queueNotificationsEnabled"],
    })
