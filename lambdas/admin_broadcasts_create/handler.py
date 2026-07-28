"""
POST /admin/broadcasts-create - Create a broadcast (admin only).

Body: {title, body, activeUntil?}
Response: {id, title, body, activeUntil, createdAt, createdBy}
"""

import uuid
from datetime import datetime, timezone

from lambdas.common.admin import require_admin
from lambdas.common.broadcasts_dynamo import put_broadcast
from lambdas.common.broadcasts_models import BroadcastCreateRequest
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.model_helpers import parse_model
from lambdas.common.utility_helpers import parse_body, success_response

log = get_logger(__file__)

HANDLER = "admin_broadcasts_create"


def _parse_epoch(active_until: str | None) -> int | None:
    if not active_until:
        return None
    try:
        normalized = active_until[:-1] if active_until.endswith("Z") else active_until
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)
    body = parse_body(event)
    request = parse_model(BroadcastCreateRequest, body, HANDLER)

    broadcast_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    item = {
        "broadcastId": broadcast_id,
        "title": request.title,
        "body": request.body,
        "activeUntil": request.activeUntil,
        "createdAt": created_at,
        "createdBy": admin_email,
    }

    ttl_epoch = _parse_epoch(request.activeUntil)
    if ttl_epoch is not None:
        item["ttl"] = ttl_epoch

    log.info(f"admin_broadcasts_create by={admin_email} id={broadcast_id}")
    put_broadcast(item)

    return success_response({
        "id": broadcast_id,
        "title": request.title,
        "body": request.body,
        "activeUntil": request.activeUntil,
        "createdAt": created_at,
        "createdBy": admin_email,
    })
