"""
GET /user/data - Get the caller's user-table row.

Caller identity comes from the trusted authorizer context (per-user JWT)
when present, falling back to the query-string `email` during the
Track-1 migration window. The endpoint returns the caller's own row only;
there is no `friendEmail` / `targetEmail` for cross-user lookups.
"""

from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.user_visibility import read_visibility
from lambdas.common.utility_helpers import (
    get_caller_email,
    success_response,
)

log = get_logger(__file__)

HANDLER = 'user_data'


@handle_errors(HANDLER)
def handler(event, context):
    caller_email = get_caller_email(event)

    response = get_user_table_data(caller_email) or {}

    # Normalized here rather than in each client. The "unset means friends"
    # rule lives in one place, because a client that gets it wrong shows
    # someone the wrong answer about who can see their data.
    response["visibility"] = read_visibility(response)

    log.info(f"Retrieved data for {caller_email}")

    return success_response(response)
