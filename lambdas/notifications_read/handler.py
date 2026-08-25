"""
POST /notifications/read — mark inbox items read.

Body:
    { "tsId": "<iso>#<rand8>" }   mark one
    { "all": true }               mark every unread item

Idempotent either way. Marking an already-read item is a no-op, and marking one
that TTL has already reaped fails the condition check and returns updated=0
rather than resurrecting a ghost row.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.notifications_dynamo import mark_all_read, mark_read
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = "notifications_read"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    email = get_caller_email(event)
    body = parse_body(event)

    mark_everything = bool(body.get("all"))
    ts_id = body.get("tsId")

    if not mark_everything and not ts_id:
        raise ValidationError(
            message="Provide either tsId or all=true",
            handler=HANDLER,
            function="handler",
            field="tsId",
        )

    if mark_everything:
        updated = mark_all_read(email)
    else:
        updated = 1 if mark_read(email, ts_id) else 0

    log.info(f"marked {updated} notification(s) read for {email}")
    return success_response({"ok": True, "updated": updated})
