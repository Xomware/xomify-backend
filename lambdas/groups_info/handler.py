"""
GET /groups/info - Get groups info
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.groups_dynamo import get_group
from lambdas.common.group_members_dynamo import list_members_of_group
from lambdas.common.group_tracks_dynamo import list_tracks_for_group

log = get_logger(__file__)

HANDLER = 'groups_info'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'groupId')

    email = get_caller_email(event)
    group_id = params.get('groupId')

    log.info(f"Getting Group {group_id} info, members and tracks. Called by {email}")

    # Run all 3 DynamoDB calls in parallel
    result = asyncio.run(fetch_group_data_parallel(group_id))

    log.info(f"Group {group_id} has {result['memberCount']} members and {result['trackCount']} tracks.")

    return success_response(result)


async def fetch_group_data_parallel(group_id: str) -> dict:
    """Fetch group data, members, and tracks in parallel."""

    # Use ThreadPoolExecutor to run sync functions in parallel
    loop = asyncio.get_event_loop()

    with ThreadPoolExecutor(max_workers=3) as executor:
        # Run all 3 calls concurrently
        group_task = loop.run_in_executor(executor, get_group, group_id)
        members_task = loop.run_in_executor(executor, list_members_of_group, group_id)
        tracks_task = loop.run_in_executor(executor, list_tracks_for_group, group_id)

        # Wait for all to complete
        group, group_members, group_tracks = await asyncio.gather(
            group_task,
            members_task,
            tracks_task
        )

    return {
        'group': group,
        'members': group_members,
        'tracks': group_tracks,
        'memberCount': len(group_members),
        'trackCount': len(group_tracks)
    }
