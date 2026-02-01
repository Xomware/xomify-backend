"""
GET /groups/list - Get user's groups
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.group_members_dynamo import list_groups_for_user

log = get_logger(__file__)

HANDLER = 'groups_list'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')

    log.info(f"Listing all groups for user {email}")
    groups = list_groups_for_user(email)
    log.info(f"Found {len(groups)} groups for user {email}")

    return success_response({
        "groups": groups,
        "totalGroups": len(groups)
    })
