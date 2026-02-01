"""
DELETE /groups/remove-member - Remove a member from group
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import get_query_params, require_fields
from lambdas.common.group_members_dynamo import remove_group_member

log = get_logger(__file__)

HANDLER = 'groups_remove_member'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email', 'groupId', 'memberEmail')

    email = params.get('email')
    group_id = params.get('groupId')
    member_email = params.get('memberEmail')

    log.info(f"User {email} removing {member_email} from group {group_id}")

    remove_group_member(member_email, group_id)

    log.info(f"Member {member_email} removed from group {group_id}")

    return {
        'statusCode': 204,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': ''
    }
