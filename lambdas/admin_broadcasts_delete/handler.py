"""
DELETE /admin/broadcasts-delete?id=... - Delete a broadcast (admin only).

Response: {deleted:true, id}
"""

from lambdas.common.admin import require_admin
from lambdas.common.broadcasts_dynamo import delete_broadcast
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_query_params,
    require_fields,
    success_response,
)

log = get_logger(__file__)

HANDLER = "admin_broadcasts_delete"


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)
    params = get_query_params(event)
    require_fields(params, "id")

    broadcast_id = params.get("id")
    log.info(f"admin_broadcasts_delete by={admin_email} id={broadcast_id}")

    delete_broadcast(broadcast_id)

    return success_response({"deleted": True, "id": broadcast_id})
