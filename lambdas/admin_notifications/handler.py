"""
GET /admin/notifications?limit= - Outbound notification log (admin only).

Response (newest first):
[
  {
    "ts": "2026-07-28T12:00:00+00:00",
    "channel": "email" | "push",
    "toEmail": "user@x.com",
    "subject": "...",
    "bodyPreview": "... (<=200 chars)",
    "status": "sent" | "failed"
  }
]
"""

from lambdas.common.admin import require_admin
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.notification_log_dynamo import list_recent_notifications
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "admin_notifications"

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _limit(params: dict) -> int:
    raw = params.get("limit")
    if raw is None:
        return _DEFAULT_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LIMIT
    return max(1, min(value, _MAX_LIMIT))


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)
    params = get_query_params(event)
    limit = _limit(params)

    rows = list_recent_notifications(limit)
    payload = [
        {
            "ts": row.get("ts"),
            "channel": row.get("channel"),
            "toEmail": row.get("toEmail"),
            "subject": row.get("subject"),
            "bodyPreview": row.get("bodyPreview"),
            "status": row.get("status"),
            "error": row.get("error"),
        }
        for row in rows
    ]

    log.info(f"admin_notifications by={admin_email} count={len(payload)} limit={limit}")
    return success_response(payload)
