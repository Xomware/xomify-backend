"""
POST /groups/leave - Leave a group
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import parse_body, require_fields
from lambdas.common.group_members_dynamo import remove_group_member

log = get_logger(__file__)

HANDLER = 'groups_leave'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'groupId')

    email = body.get('email')
    group_id = body.get('groupId')

    log.info(f"User {email} leaving group {group_id}")

    remove_group_member(email, group_id)

    log.info(f"User {email} left group {group_id}")

    return {
        'statusCode': 204,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': ''
    }
