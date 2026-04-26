"""
POST /friends/reject - Reject a friend request
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields, get_caller_email
from lambdas.common.friendships_dynamo import delete_friends

log = get_logger(__file__)

HANDLER = 'friends_reject'


@handle_errors(HANDLER)
def handler(event, context):
    email = get_caller_email(event)

    body = parse_body(event)
    require_fields(body, 'requestEmail')
    request_email = body.get('requestEmail')

    log.info(f"User {email} is rejecting friend request from {request_email}.")
    success = delete_friends(email, request_email)
    log.info(f"Friend Request Rejected {'Success!' if success else 'Failure!'}")

    return success_response({'success': success})
