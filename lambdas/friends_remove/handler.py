"""
DELETE /friends/remove - Remove a friend
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields, get_caller_email
from lambdas.common.friendships_dynamo import delete_friends

log = get_logger(__file__)

HANDLER = 'friends_remove'


@handle_errors(HANDLER)
def handler(event, context):
    email = get_caller_email(event)

    params = get_query_params(event)
    require_fields(params, 'friendEmail')
    friend_email = params.get('friendEmail')

    log.info(f"User {email} is removing friend {friend_email}.")
    success = delete_friends(email, friend_email)
    log.info(f"Friend Removed {'Success!' if success else 'Failure!'}")

    return success_response({'success': success})
