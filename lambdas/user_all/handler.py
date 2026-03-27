"""
GET /user/all - Get all users
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan

log = get_logger(__file__)

HANDLER = 'user_all'


@handle_errors(HANDLER)
def handler(event, context):
    users = full_table_scan(USERS_TABLE_NAME)

    # Remove sensitive data
    clean_users = []
    for user in users:
        user.pop('refreshToken', None)
        clean_users.append(user)

    log.info(f"Retrieved {len(clean_users)} users from user table")

    return success_response(clean_users)
