"""
GET /friends/all - Get all friends from friendship table
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from lambdas.common.constants import FRIENDSHIPS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan

log = get_logger(__file__)

HANDLER = 'friends_all'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("Getting all friends from table.")
    friends = full_table_scan(FRIENDSHIPS_TABLE_NAME)

    return success_response({
        'friends': friends,
        'totalFriends': len(friends)
    })
