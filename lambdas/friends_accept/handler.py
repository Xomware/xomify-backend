"""
POST /friends/accept - Accept a friend request
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.friendships_dynamo import accept_friend_request

log = get_logger(__file__)

HANDLER = 'friends_accept'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'requestEmail')

    email = body.get('email')
    request_email = body.get('requestEmail')

    log.info(f"User {email} is accepting friend request from {request_email}.")
    success = accept_friend_request(email, request_email)
    log.info(f"Friend Request Accepted {'Success!' if success else 'Failure!'}")

    return success_response({'success': success})
