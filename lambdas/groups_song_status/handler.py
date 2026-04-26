"""
PUT /groups/song-status - Update user's status on a song
"""

from datetime import datetime, timezone
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.group_tracks_dynamo import mark_track_as_listened

log = get_logger(__file__)

HANDLER = 'groups_song_status'


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'groupId', 'songId')

    email = get_caller_email(event)
    group_id = body.get('groupId')
    song_id = body.get('songId')  # This is the trackIdTimestamp (SK)
    listened = body.get('listened', False)
    added_to_queue = body.get('addedToQueue', False)

    log.info(f"User {email} updating status for song {song_id} in group {group_id}")

    # Update listened status
    if listened:
        mark_track_as_listened(group_id, song_id, email)

    # Note: addedToQueue would need a separate DynamoDB attribute
    # For now, we'll just return the status

    response_data = {
        'songId': song_id,
        'email': email,
        'addedToQueue': added_to_queue,
        'listened': listened
    }

    if added_to_queue:
        response_data['queuedAt'] = _get_timestamp()

    if listened:
        response_data['listenedAt'] = _get_timestamp()

    log.info(f"Status updated for user {email} on song {song_id}")

    return success_response(response_data)
