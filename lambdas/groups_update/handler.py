"""
PUT /groups/update - Update group details
"""

import boto3
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.constants import GROUPS_TABLE_NAME
from lambdas.common.groups_dynamo import get_group
from lambdas.common.group_members_dynamo import list_members_of_group

log = get_logger(__file__)

HANDLER = 'groups_update'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'groupId')

    email = get_caller_email(event)
    group_id = body.get('groupId')
    name = body.get('name')
    description = body.get('description')

    # Verify user is admin
    members = list_members_of_group(group_id)
    user_member = next((m for m in members if m['email'] == email), None)

    if not user_member or user_member.get('role') != 'owner':
        raise ValidationError("Only group owner can update group", field="email")

    # Build update expression.
    # `name` is a DynamoDB reserved keyword, so we alias both attributes via
    # ExpressionAttributeNames to stay safe regardless of future renames.
    update_parts = []
    attr_values = {}
    attr_names = {}

    if name:
        update_parts.append("#name = :name")
        attr_values[':name'] = name
        attr_names['#name'] = 'name'

    if description is not None:
        update_parts.append("#desc = :desc")
        attr_values[':desc'] = description
        attr_names['#desc'] = 'description'

    if not update_parts:
        raise ValidationError("No fields to update")

    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(GROUPS_TABLE_NAME)

    table.update_item(
        Key={'groupId': group_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeValues=attr_values,
        ExpressionAttributeNames=attr_names
    )

    log.info(f"Group {group_id} updated by {email}")

    # Get updated group
    updated_group = get_group(group_id)

    return success_response(updated_group)
