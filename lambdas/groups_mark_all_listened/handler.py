"""
POST /groups/mark-all-listened - Mark all songs as listened for user
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.group_tracks_dynamo import list_tracks_for_group, mark_track_as_listened

log = get_logger(__file__)

HANDLER = 'groups_mark_all_listened'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'groupId')

    email = get_caller_email(event)
    group_id = body.get('groupId')

    log.info(f"User {email} marking all songs as listened in group {group_id}")

    # Get all tracks for group
    tracks = list_tracks_for_group(group_id)

    # Mark each as listened
    count = 0
    for track in tracks:
        track_id_timestamp = track.get('trackIdTimestamp')
        listened_by = track.get('listenedBy', set())

        # Only mark if not already listened
        if email not in listened_by:
            try:
                mark_track_as_listened(group_id, track_id_timestamp, email)
                count += 1
            except Exception as err:
                log.warning(f"Failed to mark {track_id_timestamp} as listened: {err}")

    log.info(f"Marked {count} songs as listened for user {email} in group {group_id}")

    return success_response({'count': count})
