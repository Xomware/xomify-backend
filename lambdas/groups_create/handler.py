"""
POST /groups/create - Create a new group
"""

import uuid
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.groups_dynamo import create_group
from lambdas.common.group_members_dynamo import add_group_member

log = get_logger(__file__)

HANDLER = 'groups_create'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'name')

    email = body.get('email')
    name = body.get('name')
    description = body.get('description')
    image_url = body.get('imageUrl')
    member_emails = body.get('memberEmails', [])

    # Generate group ID
    group_id = str(uuid.uuid4())

    log.info(f"Creating group '{name}' for {email}")

    # Create group
    create_group(group_id, name, email, image_url)

    # Add creator as owner
    add_group_member(email, group_id, role="owner")

    # Add additional members
    for member_email in member_emails:
        if member_email != email:  # Don't add creator twice
            try:
                add_group_member(member_email, group_id, role="member")
            except Exception as err:
                log.warning(f"Failed to add member {member_email}: {err}")

    log.info(f"Group {group_id} created with {len(member_emails) + 1} members")

    return success_response({
        'groupId': group_id,
        'name': name,
        'createdBy': email,
        'description': description,
        'imageUrl': image_url
    })
