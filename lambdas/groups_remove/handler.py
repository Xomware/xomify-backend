"""
DELETE /groups/remove - Delete a group (owner only)
"""

import boto3
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.constants import GROUPS_TABLE_NAME
from lambdas.common.group_members_dynamo import list_members_of_group

log = get_logger(__file__)

HANDLER = 'groups_remove'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'groupId')

    email = get_caller_email(event)
    group_id = params.get('groupId')

    # Verify user is owner
    members = list_members_of_group(group_id)
    user_member = next((m for m in members if m['email'] == email), None)

    if not user_member or user_member.get('role') != 'owner':
        raise ValidationError("Only group owner can delete group", field="email")

    # Delete group
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(GROUPS_TABLE_NAME)
    table.delete_item(Key={'groupId': group_id})

    log.info(f"Group {group_id} deleted by {email}")

    return {
        'statusCode': 204,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': ''
    }
