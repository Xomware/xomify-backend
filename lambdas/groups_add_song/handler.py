"""
POST /groups/add-song - Add a song to group (with track data)
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.group_tracks_dynamo import add_track_to_group

log = get_logger(__file__)

HANDLER = 'groups_add_song'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'groupId', 'trackId', 'track')

    email = body.get('email')
    group_id = body.get('groupId')
    track_id = body.get('trackId')
    track = body.get('track')

    # Extract track details
    track_name = track.get('name')
    artists = track.get('artists', [])
    artist_name = artists[0].get('name') if artists else None
    album = track.get('album', {})
    images = album.get('images', [])
    album_image_url = images[0].get('url') if images else None

    log.info(f"User {email} adding track {track_id} to group {group_id}")

    add_track_to_group(
        group_id=group_id,
        track_id=track_id,
        added_by=email,
        track_name=track_name,
        artist_name=artist_name,
        album_image_url=album_image_url
    )

    log.info(f"Track {track_id} added to group {group_id}")

    return success_response({
        'groupId': group_id,
        'trackId': track_id,
        'addedBy': email,
        'trackName': track_name,
        'artistName': artist_name,
        'albumImageUrl': album_image_url
    })
