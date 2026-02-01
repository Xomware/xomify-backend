"""
POST /groups/add-member - Add a member to group
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.group_members_dynamo import add_group_member
from lambdas.common.dynamo_helpers import get_user_table_data

log = get_logger(__file__)

HANDLER = 'groups_add_member'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'groupId', 'memberEmail')

    email = body.get('email')
    group_id = body.get('groupId')
    member_email = body.get('memberEmail')

    log.info(f"User {email} adding {member_email} to group {group_id}")

    # Add member
    add_group_member(member_email, group_id, role="member")

    # Get member data
    member_data = get_user_table_data(member_email)

    log.info(f"Member {member_email} added to group {group_id}")

    return success_response({
        'email': member_email,
        'displayName': member_data.get('displayName') if member_data else None,
        'avatar': member_data.get('avatar') if member_data else None,
        'role': 'member'
    })
