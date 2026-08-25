"""
GET /notifications?limit=&cursor= — one page of the caller's inbox.

Newest first. `cursor` is the `tsId` of the last item the client already holds;
pass back `nextCursor` from the previous response. `nextCursor` is null on the
last page.

Caller identity comes from the authorizer context via `get_caller_email` — the
inbox is strictly self-scoped and takes no email parameter, so there is nothing
to spoof.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.notifications_dynamo import list_notifications
from lambdas.common.utility_helpers import get_caller_email, success_response

log = get_logger(__file__)

HANDLER = "notifications_feed"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    email = get_caller_email(event)
    params = event.get("queryStringParameters") or {}

    raw_limit = params.get("limit")
    try:
        limit = int(raw_limit) if raw_limit else 25
    except (TypeError, ValueError):
        # A junk limit is not worth a 400 — fall back to the default page.
        limit = 25

    page = list_notifications(email, limit=limit, cursor=params.get("cursor"))
    log.info(f"inbox page for {email}: {len(page['items'])} items")

    return success_response({
        "items": page["items"],
        "nextCursor": page["nextCursor"],
    })
