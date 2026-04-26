"""
POST /groups/add-song-url - Add a song by Spotify URL
"""

import re
import aiohttp
import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.group_tracks_dynamo import add_track_to_group
from lambdas.common.spotify import Spotify

log = get_logger(__file__)

HANDLER = 'groups_add_song_url'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'groupId', 'spotifyUrl')

    email = get_caller_email(event)
    group_id = body.get('groupId')
    spotify_url = body.get('spotifyUrl')

    # Extract track ID from URL
    track_id = extract_track_id(spotify_url)
    if not track_id:
        raise ValidationError("Invalid Spotify URL", field="spotifyUrl")

    log.info(f"User {email} adding track {track_id} from URL to group {group_id}")

    # Get track details from Spotify
    result = asyncio.run(fetch_track_details(email, track_id, group_id))

    return success_response(result)


def extract_track_id(url: str) -> str | None:
    """Extract track ID from Spotify URL."""
    patterns = [
        r'track/([a-zA-Z0-9]+)',
        r'spotify:track:([a-zA-Z0-9]+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


async def fetch_track_details(email: str, track_id: str, group_id: str) -> dict:
    """Fetch track details from Spotify and add to group."""

    from lambdas.common.dynamo_helpers import get_user_table_data
    user = get_user_table_data(email)

    async with aiohttp.ClientSession() as session:
        spotify = Spotify(user, session)
        access_token = await spotify.aiohttp_get_access_token()

        # Fetch track details
        headers = {'Authorization': f'Bearer {access_token}'}
        url = f"https://api.spotify.com/v1/tracks/{track_id}"

        async with session.get(url, headers=headers) as response:
            status = response.status
            track = await response.json()

        if status != 200:
            raise ValidationError("Track not found", field="spotifyUrl")

        # Extract track details
        track_name = track.get('name')
        artists = track.get('artists', [])
        artist_name = artists[0].get('name') if artists else None
        album = track.get('album', {})
        images = album.get('images', [])
        album_image_url = images[0].get('url') if images else None

        # Add to group
        add_track_to_group(
            group_id=group_id,
            track_id=track_id,
            added_by=email,
            track_name=track_name,
            artist_name=artist_name,
            album_image_url=album_image_url
        )

        return {
            'groupId': group_id,
            'trackId': track_id,
            'addedBy': email,
            'trackName': track_name,
            'artistName': artist_name,
            'albumImageUrl': album_image_url
        }
