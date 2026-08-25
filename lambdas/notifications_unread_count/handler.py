"""
GET /notifications/unread-count — badge count for the caller.

Split from the feed endpoint on purpose: a client polls this far more often
than it opens the inbox, and it should not have to transfer a page of items to
render a number.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.notifications_dynamo import count_unread
from lambdas.common.utility_helpers import get_caller_email, success_response

log = get_logger(__file__)

HANDLER = "notifications_unread_count"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    email = get_caller_email(event)
    return success_response({"unread": count_unread(email)})
