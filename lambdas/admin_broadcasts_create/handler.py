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
import json
import boto3
from lambdas.common.constants import BROADCAST_FANOUT_FUNCTION_NAME

_lambda_client = boto3.client("lambda")


def _dispatch_broadcast_push(broadcast_id: str, title: str, body_text: str) -> None:
    """
    Hand the fan-out to a dedicated lambda, asynchronously.

    Deliberately NOT done inline: reaching every user means a full users-table
    scan plus one dispatch each. Inside this request handler the admin would
    wait on all of it, and it would get quietly slower until it hit the
    gateway timeout with no feedback. Fire-and-forget — the broadcast row is
    already persisted, so a failed push never costs the broadcast itself.
    """
    if not BROADCAST_FANOUT_FUNCTION_NAME:
        log.warning("BROADCAST_FANOUT_FUNCTION_NAME unset — skipping broadcast push")
        return
    try:
        _lambda_client.invoke(
            FunctionName=BROADCAST_FANOUT_FUNCTION_NAME,
            InvocationType="Event",
            Payload=json.dumps({
                "broadcastId": broadcast_id,
                "title": title,
                "body": body_text,
            }).encode("utf-8"),
        )
        log.info(f"broadcast fan-out dispatched for {broadcast_id}")
    except Exception as err:  # noqa: BLE001
        log.error(f"Failed to dispatch broadcast fan-out: {err}")


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

    _dispatch_broadcast_push(broadcast_id, request.title, request.body)

    return success_response({
        "id": broadcast_id,
        "title": request.title,
        "body": request.body,
        "activeUntil": request.activeUntil,
        "createdAt": created_at,
        "createdBy": admin_email,
    })
