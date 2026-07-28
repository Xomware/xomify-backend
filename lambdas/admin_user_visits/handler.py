"""
GET /admin/user-visits?email= - Page-visit history for one user (admin only).

Response: [{"ts": "2026-07-28T12:00:00+00:00", "path": "/home"}]  (newest first)
"""

from lambdas.common.admin import require_admin
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import get_query_params, success_response
from lambdas.common.visits_dynamo import list_visits_for_user

log = get_logger(__file__)

HANDLER = "admin_user_visits"


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)
    params = get_query_params(event)

    email = params.get("email")
    if not email:
        raise ValidationError("email is required", handler=HANDLER, field="email")

    rows = list_visits_for_user(email)
    payload = [
        {"ts": row.get("visitedAt") or row.get("ts"), "path": row.get("path")}
        for row in rows
    ]

    log.info(f"admin_user_visits by={admin_email} email={email} count={len(payload)}")
    return success_response(payload)
