"""
Internal-invoke lambda — notifications_send

Event shape:
    {
        "kind":  "queue_threshold" | "digest",
        "email": "recipient@...",
        "title": "...",
        "body":  "...",
        "customData": { ... } (optional)
    }

Flow:
    1. Look up all device tokens for the recipient email.
    2. Filter by the relevant opt-in flag (queueNotificationsEnabled for
       queue_threshold, digestEnabled for digest).
    3. Dispatch one APNs push per token via ApnsClient.
    4. Prune any token that APNs responds to with 410 Unregistered.

Returns: {"sent": n, "failed": m, "pruned": p, "skipped": s}
"""

from __future__ import annotations

from typing import Any

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import success_response
from lambdas.common.device_tokens_dynamo import delete_token, list_tokens_for_user
from lambdas.common.apns_client import get_client

log = get_logger(__file__)

HANDLER = "notifications_send"

VALID_KINDS = {"queue_threshold", "digest"}
OPT_IN_FLAG_BY_KIND = {
    "queue_threshold": "queueNotificationsEnabled",
    "digest": "digestEnabled",
}


def _coerce_event(event: dict) -> dict:
    """Accept both API Gateway shape and direct-invoke payload shape."""
    if isinstance(event, dict) and isinstance(event.get("body"), str):
        import json
        try:
            return json.loads(event["body"])
        except Exception:
            return {}
    return event or {}


@handle_errors(HANDLER)
def handler(event, context):
    payload = _coerce_event(event)

    kind = payload.get("kind")
    email = payload.get("email")
    title = payload.get("title")
    body_text = payload.get("body")
    custom_data = payload.get("customData") or {}

    if kind not in VALID_KINDS:
        raise ValidationError(
            message=f"Invalid kind '{kind}'. Must be one of: {sorted(VALID_KINDS)}",
            handler=HANDLER,
            function="handler",
            field="kind",
        )
    if not email:
        raise ValidationError(
            message="email is required",
            handler=HANDLER,
            function="handler",
            field="email",
        )
    if not title or not body_text:
        raise ValidationError(
            message="title and body are required",
            handler=HANDLER,
            function="handler",
            field="title",
        )

    tokens = list_tokens_for_user(email)
    opt_in_flag = OPT_IN_FLAG_BY_KIND[kind]

    sent = 0
    failed = 0
    pruned = 0
    skipped = 0

    client = get_client()

    for row in tokens:
        # Default to True if the flag is absent (legacy rows).
        if not bool(row.get(opt_in_flag, True)):
            skipped += 1
            continue

        device_token = row.get("deviceToken")
        if not device_token:
            skipped += 1
            continue

        try:
            result: dict[str, Any] = client.send(
                device_token=device_token,
                alert_title=title,
                alert_body=body_text,
                category=payload.get("category"),
                custom_data=custom_data,
                collapse_id=payload.get("collapseId"),
            )
        except Exception as err:
            log.error(f"APNs send threw for {email}: {err}")
            failed += 1
            continue

        status = result.get("statusCode")
        if result.get("ok"):
            sent += 1
        else:
            failed += 1
            if status == 410:
                # Unregistered — prune the token.
                try:
                    delete_token(email=email, device_token=device_token)
                    pruned += 1
                    log.info(f"Pruned 410-Unregistered token for {email}")
                except Exception as err:
                    log.warning(f"Failed to prune 410 token for {email}: {err}")

    return success_response({
        "email": email,
        "kind": kind,
        "sent": sent,
        "failed": failed,
        "pruned": pruned,
        "skipped": skipped,
    })
