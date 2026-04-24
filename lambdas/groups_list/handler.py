"""
GET /groups/list - Get user's groups

Returns fully-hydrated group objects. The membership table only stores
(email, groupId, role, joinedAt), so we BatchGetItem the GROUPS table to
attach name / createdBy / memberCount / etc. Without this join, clients
see headless membership rows and fail to decode.

memberCount is recomputed LIVE from the membership GSI on every call.
The cached `memberCount` attribute on the GROUPS row was historically
populated by a buggy seed that set fresh 1-member groups to 2 (fixed by
PR #136 for new groups but never backfilled). To avoid showing stale
counts to users we always recount, and opportunistically heal the row
with a best-effort write-back (log and continue on failure — this path
must never break /groups/list).
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.group_members_dynamo import list_groups_for_user, list_members_of_group
from lambdas.common.groups_dynamo import batch_get_groups, update_group_member_count

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

        # Recount members live — stale cached memberCount is the whole reason
        # we're here. N+1 reads are acceptable because a user's group count is
        # small (typically < 20); the alternative is shipping wrong numbers.
        try:
            members = list_members_of_group(gid)
            live_count = len(members)
        except Exception as err:
            log.warning(
                f"Live recount failed for group {gid}, "
                f"falling back to cached memberCount: {err}"
            )
            live_count = merged.get("memberCount", 0)

        cached = merged.get("memberCount")
        merged["memberCount"] = live_count

        # Opportunistic heal: if the cached value drifted, write the live
        # count back so future reads don't have to recount. Never let this
        # break the request.
        if cached != live_count:
            try:
                update_group_member_count(gid, live_count)
                log.info(
                    f"Healed stale memberCount on group {gid}: "
                    f"cached={cached} -> live={live_count}"
                )
            except Exception as err:
                log.warning(
                    f"memberCount heal failed for group {gid} "
                    f"(cached={cached} live={live_count}): {err}"
                )

        hydrated.append(merged)

    return success_response({
        "groups": hydrated,
        "totalGroups": len(hydrated)
    })
