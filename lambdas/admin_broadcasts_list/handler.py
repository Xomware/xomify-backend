"""
GET /admin/broadcasts-list - List every broadcast (admin only).

Response: {broadcasts:[{id, title, body, activeUntil, createdAt, createdBy}]}
"""

from lambdas.common.admin import require_admin
from lambdas.common.broadcasts_dynamo import get_all_broadcasts
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "admin_broadcasts_list"


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)

    broadcasts = get_all_broadcasts()
    log.info(f"admin_broadcasts_list by={admin_email} total={len(broadcasts)}")

    payload = [
        {
            "id": b.get("broadcastId"),
            "title": b.get("title"),
            "body": b.get("body"),
            "activeUntil": b.get("activeUntil"),
            "createdAt": b.get("createdAt"),
            "createdBy": b.get("createdBy"),
        }
        for b in broadcasts
    ]

    return success_response({"broadcasts": payload})
