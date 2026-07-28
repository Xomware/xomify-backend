"""
GET /favorites/list-history?listId=... - Rank-change history for a list.

Response: {listId, events:[{ts, spotifyId, fromRank, toRank}]}   # chronological asc
"""

from lambdas.common.errors import handle_errors
from lambdas.common.favorites_dynamo import get_history
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    require_fields,
    success_response,
)

log = get_logger(__file__)

HANDLER = "favorites_list_history"


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, "listId")

    email = get_caller_email(event)
    list_id = params.get("listId")

    log.info(f"favorites_list_history email={email} listId={list_id}")

    rows = get_history(email, list_id)
    events = [
        {
            "ts": row.get("ts"),
            "spotifyId": row.get("spotifyId"),
            "fromRank": row.get("fromRank"),
            "toRank": row.get("toRank"),
        }
        for row in rows
    ]

    return success_response({"listId": list_id, "events": events})
