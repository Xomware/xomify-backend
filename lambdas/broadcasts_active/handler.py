"""
GET /broadcasts/active - Currently-active broadcasts (any authed user).

Response: {broadcasts:[{id, title, body, activeUntil, createdAt}]}
"""

from lambdas.common.broadcasts_dynamo import get_active_broadcasts
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import get_caller_email, success_response

log = get_logger(__file__)

HANDLER = "broadcasts_active"


@handle_errors(HANDLER)
def handler(event, context):
    # Enforces authentication (raises 401 if identity is unresolved).
    email = get_caller_email(event)

    broadcasts = get_active_broadcasts()
    log.info(f"broadcasts_active email={email} active={len(broadcasts)}")

    payload = [
        {
            "id": b.get("broadcastId"),
            "title": b.get("title"),
            "body": b.get("body"),
            "activeUntil": b.get("activeUntil"),
            "createdAt": b.get("createdAt"),
        }
        for b in broadcasts
    ]

    return success_response({"broadcasts": payload})
