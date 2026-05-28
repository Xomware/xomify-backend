"""
GET /friends/all - Get all friends from friendship table
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_caller_email
from lambdas.common.constants import FRIENDSHIPS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan

log = get_logger(__file__)

HANDLER = 'friends_all'


@handle_errors(HANDLER)
def handler(event, context):
    # Require an authenticated caller. get_caller_email raises if the request
    # carries no valid identity, so an unauthenticated request can never reach
    # the full-table scan below.
    email = get_caller_email(event)

    log.info(f"Getting all friends from table for caller {email}.")
    friends = full_table_scan(FRIENDSHIPS_TABLE_NAME)

    return success_response({
        'friends': friends,
        'totalFriends': len(friends)
    })
