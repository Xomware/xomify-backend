"""
GET /friends/pending - Get pending friend requests
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_caller_email
from lambdas.common.friendships_dynamo import list_all_friends_for_user

log = get_logger(__file__)

HANDLER = 'friends_pending'


@handle_errors(HANDLER)
def handler(event, context):
    email = get_caller_email(event)

    log.info(f"Getting all pending friends for user {email}")
    friends = list_all_friends_for_user(email)

    pending = []
    for friend in friends:
        if friend['status'] == 'pending':
            pending.append(friend)

    return success_response({
        'email': email,
        'pendingCount': len(pending),
        'pending': pending,
    })
