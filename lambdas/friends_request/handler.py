"""
POST /friends/request - Send a friend request
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.friendships_dynamo import send_friend_request

log = get_logger(__file__)

HANDLER = 'friends_request'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'requestEmail')

    email = body.get('email')
    request_email = body.get('requestEmail')

    log.info(f"User {email} is sending request to {request_email} to be a friend.")
    success = send_friend_request(email, request_email)
    log.info(f"Friend Request {'Success!' if success else 'Failure!'}")

    return success_response({'success': success})
