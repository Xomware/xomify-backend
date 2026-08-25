"""
Internal-invoke lambda — notifications_broadcast_fanout

Sends one admin broadcast to every active user.

WHY THIS IS ITS OWN LAMBDA AND NOT INLINE IN admin_broadcasts_create:
fanning out to every user means a full scan of the users table plus one
dispatch per user. Doing that inside the admin's request handler means the
admin waits on it, and — worse — it silently gets slower as the user base
grows until one day it hits the API Gateway timeout with no feedback at all.
Async invoke moves it off the request path entirely; the admin's broadcast is
persisted and returned immediately either way.

Event shape:
    {
        "broadcastId": "<uuid>",
        "title": "...",
        "body":  "..."
    }

Returns: {"notified": n, "skipped": s}
"""

from __future__ import annotations

from typing import Any

from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.notify import notify
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "notifications_broadcast_fanout"

#: Ceiling per invocation. Far above any realistic user count for this app; it
#: exists so a runaway scan degrades into a truncated send with a loud log
#: rather than a timeout that delivers nothing.
MAX_RECIPIENTS = 5000


def _coerce_event(event: dict) -> dict:
    """
    Accept both the API Gateway shape and a direct-invoke payload.

    THE SUBTLETY THAT BIT THIS BEFORE: the direct-invoke payload has its OWN
    `body` key — the notification's body text — which collides with API
    Gateway's `body` envelope. The previous version saw a string under `body`,
    tried to `json.loads` it, failed on ordinary prose like
    "2 friends have queued Midnight City", and returned `{}`. Every direct
    invoke was then rejected as missing its required fields, so nothing ever
    sent.

    Only unwrap when the string actually parses to a dict. Prose does not.
    """
    if not isinstance(event, dict):
        return {}
    raw = event.get("body")
    if isinstance(raw, str):
        import json
        try:
            parsed = json.loads(raw)
        except Exception:
            return event
        # A parsed scalar means `body` was the notification text, not an
        # envelope — keep the original event.
        return parsed if isinstance(parsed, dict) else event
    return event


@handle_errors(HANDLER)
def handler(event, context):
    payload = _coerce_event(event)

    title = payload.get("title")
    body_text = payload.get("body")
    broadcast_id = payload.get("broadcastId")

    if not title or not body_text:
        raise ValidationError(
            message="title and body are required",
            handler=HANDLER,
            function="handler",
            field="title",
        )

    users: list[dict[str, Any]] = full_table_scan(USERS_TABLE_NAME) or []

    notified = 0
    skipped = 0

    for user in users:
        email = user.get("email")
        # Same `active` gate cron_favorites_reminder uses — there is no separate
        # broadcast enrolment flag, and inventing one here would diverge.
        if not email or not user.get("active"):
            skipped += 1
            continue

        if notified >= MAX_RECIPIENTS:
            log.warning(f"broadcast fan-out capped at {MAX_RECIPIENTS}")
            break

        # notify() is fail-open per recipient, so one bad row cannot strand the
        # rest of the broadcast.
        notify(
            "broadcast",
            email,
            broadcast_title=title,
            broadcast_body=body_text,
            broadcast_id=broadcast_id,
        )
        notified += 1

    stats = {"notified": notified, "skipped": skipped}
    log.info(f"broadcast fan-out {broadcast_id}: {stats}")
    return success_response(stats, is_api=False)
