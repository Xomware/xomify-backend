"""
GET /groups/list - Get user's groups

Returns fully-hydrated group objects. The membership table only stores
(email, groupId, role, joinedAt), so we BatchGetItem the GROUPS table to
attach name / createdBy / memberCount / etc. Without this join, clients
see headless membership rows and fail to decode.
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.group_members_dynamo import list_groups_for_user
from lambdas.common.groups_dynamo import batch_get_groups

log = get_logger(__file__)

HANDLER = 'groups_list'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')

    log.info(f"Listing all groups for user {email}")
    memberships = list_groups_for_user(email)
    log.info(f"Found {len(memberships)} memberships for user {email}")

    group_ids = [m.get("groupId") for m in memberships if m.get("groupId")]
    group_items = batch_get_groups(group_ids)
    group_by_id = {g["groupId"]: g for g in group_items if g.get("groupId")}

    # Merge membership metadata (role, joinedAt) into the hydrated group
    # object so clients get both the group state and the caller's relationship
    # in one payload. Drops memberships whose group has been deleted.
    hydrated = []
    for m in memberships:
        gid = m.get("groupId")
        group = group_by_id.get(gid)
        if not group:
            log.warning(f"Membership references missing group {gid}; dropping")
            continue
        merged = {**group}
        if "role" in m:
            merged["role"] = m["role"]
        if "joinedAt" in m:
            merged["joinedAt"] = m["joinedAt"]
        hydrated.append(merged)

    return success_response({
        "groups": hydrated,
        "totalGroups": len(hydrated)
    })
