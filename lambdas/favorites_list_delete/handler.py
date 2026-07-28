"""
DELETE /favorites/list-delete?listId=...&year=YYYY - Delete a favorites list row.

Response: {deleted:true, listId}
History rows are left in place (harmless, append-only audit trail).
"""

from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.favorites_dynamo import delete_list
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    require_fields,
    success_response,
)

log = get_logger(__file__)

HANDLER = "favorites_list_delete"


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, "listId", "year")

    email = get_caller_email(event)
    list_id = params.get("listId")

    try:
        year = int(params.get("year"))
    except (TypeError, ValueError):
        raise ValidationError("year must be an integer", handler=HANDLER, field="year")

    log.info(f"favorites_list_delete email={email} year={year} listId={list_id}")

    delete_list(email, year, list_id)

    return success_response({"deleted": True, "listId": list_id})
