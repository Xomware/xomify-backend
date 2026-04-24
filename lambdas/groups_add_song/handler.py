"""
POST /groups/add-song - Add a song to group (with track data).

Accepts two request shapes so iOS and legacy web callers can share the
endpoint:

1. Nested (legacy):
    {
        email, groupId, trackId,
        track: {
            name,
            artists: [{name}],
            album:  {images: [{url}]}
        }
    }

2. Flat (iOS client):
    {
        email, groupId, trackId,
        trackName, artistName, albumName, imageUrl
    }

email / groupId / trackId are required in both shapes. All other track
metadata is optional — a missing field just won't be persisted.
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.group_tracks_dynamo import add_track_to_group

log = get_logger(__file__)

HANDLER = 'groups_add_song'


def _extract_track_fields(body: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (trackName, artistName, albumName, imageUrl) regardless of shape.

    Prefer the nested `track` object when present (legacy callers), fall back
    to the flat top-level fields (iOS)."""
    track = body.get('track')
    if isinstance(track, dict):
        track_name = track.get('name')
        artists = track.get('artists') or []
        artist_name = artists[0].get('name') if artists and isinstance(artists[0], dict) else None
        album = track.get('album') or {}
        album_name = album.get('name') if isinstance(album, dict) else None
        images = album.get('images') or [] if isinstance(album, dict) else []
        image_url = images[0].get('url') if images and isinstance(images[0], dict) else None
        return track_name, artist_name, album_name, image_url

    # Flat shape — iOS client
    return (
        body.get('trackName'),
        body.get('artistName'),
        body.get('albumName'),
        body.get('imageUrl'),
    )


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'groupId', 'trackId')

    email = body.get('email')
    group_id = body.get('groupId')
    track_id = body.get('trackId')

    track_name, artist_name, album_name, image_url = _extract_track_fields(body)

    log.info(
        f"User {email} adding track {track_id} to group {group_id} "
        f"(trackName={track_name!r} artistName={artist_name!r})"
    )

    add_track_to_group(
        group_id=group_id,
        track_id=track_id,
        added_by=email,
        track_name=track_name,
        artist_name=artist_name,
        album_image_url=image_url,
    )

    log.info(f"Track {track_id} added to group {group_id}")

    return success_response({
        'groupId': group_id,
        'trackId': track_id,
        'addedBy': email,
        'trackName': track_name,
        'artistName': artist_name,
        'albumName': album_name,
        'albumImageUrl': image_url,
    })
