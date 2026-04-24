"""
GET /user/all - Get all users

When called with `?email=<me>`, filters the caller out of the result so
discovery UIs never show "add yourself" as an option.
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params
from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan

log = get_logger(__file__)

HANDLER = 'user_all'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    caller_email = (params.get('email') or '').strip().lower()

    users = full_table_scan(USERS_TABLE_NAME)

    clean_users = []
    for user in users:
        user.pop('refreshToken', None)
        if caller_email and (user.get('email') or '').strip().lower() == caller_email:
            continue
        clean_users.append(user)

    log.info(
        f"Retrieved {len(clean_users)} users from user table "
        f"(caller={'<anon>' if not caller_email else caller_email})"
    )

    return success_response(clean_users)
