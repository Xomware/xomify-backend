"""
GET /release-radar/history - Get user's release radar history
"""

from collections import defaultdict

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.release_radar_dynamo import (
    get_user_release_radar_history,
    get_week_key,
    format_week_display
)

log = get_logger(__file__)

HANDLER = 'release_radar_history'


def group_releases(releases: list) -> list:
    """
    Group a flat releases list into an artist -> albums structure.

    Releases stored in DynamoDB are album-level objects with fields:
        albumId, albumName, albumType, artistId, artistName,
        releaseDate, totalTracks, imageUrl, spotifyUrl, uri

    Returns:
        List of artist objects sorted alphabetically by artist name.
        Each artist contains an ``albums`` list sorted by releaseDate descending.

    Example output::

        [
            {
                "artistName": "Taylor Swift",
                "artistId": "06HL4z0CvFAxyc27GXpf02",
                "albums": [
                    {
                        "name": "The Tortured Poets Department",
                        "id": "5H7ixXZfsNMGbIE5OBSpcb",
                        "releaseDate": "2024-04-19",
                        "type": "album",
                        "uri": "spotify:album:5H7ixXZfsNMGbIE5OBSpcb",
                        "imageUrl": "https://i.scdn.co/image/...",
                        "totalTracks": 31,
                        "spotifyUrl": "https://open.spotify.com/album/..."
                    }
                ]
            }
        ]
    """
    artist_map: dict = defaultdict(lambda: {"name": "", "id": "", "albums": {}})

    for release in releases:
        artist_id = release.get('artistId') or release.get('artist_id', '')
        artist_name = release.get('artistName') or release.get('artist_name', 'Unknown Artist')
        album_id = release.get('albumId') or release.get('album_id', '')
        album_name = release.get('albumName') or release.get('album_name', 'Unknown Album')
        release_date = release.get('releaseDate') or release.get('release_date', '')

        artist_map[artist_id]['name'] = artist_name
        artist_map[artist_id]['id'] = artist_id

        if album_id not in artist_map[artist_id]['albums']:
            artist_map[artist_id]['albums'][album_id] = {
                'name': album_name,
                'id': album_id,
                'releaseDate': release_date,
                'type': release.get('albumType') or release.get('album_type', 'album'),
                'uri': release.get('uri', ''),
                'imageUrl': release.get('imageUrl') or release.get('image_url', ''),
                'totalTracks': release.get('totalTracks') or release.get('total_tracks', 1),
                'spotifyUrl': release.get('spotifyUrl') or release.get('spotify_url', ''),
            }

    # Build sorted output: artists alphabetical, albums newest-first
    grouped = []
    for artist_id, artist_data in sorted(
        artist_map.items(), key=lambda kv: kv[1]['name'].lower()
    ):
        albums = sorted(
            artist_data['albums'].values(),
            key=lambda a: a['releaseDate'],
            reverse=True,
        )
        grouped.append({
            'artistName': artist_data['name'],
            'artistId': artist_data['id'],
            'albums': albums,
        })

    return grouped


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')
    limit = int(params.get('limit', 26))

    weeks = get_user_release_radar_history(email, limit=limit)

    # Enrich each week with display name, sorted flat list, and grouped structure
    for week in weeks:
        week['weekDisplay'] = format_week_display(week.get('weekKey', ''))
        releases = week.get('releases', [])

        # Sort flat list by releaseDate descending (newest first)
        week['releases'] = sorted(
            releases,
            key=lambda r: r.get('releaseDate') or r.get('release_date', ''),
            reverse=True,
        )

        # Add grouped structure (backwards-compatible new field)
        week['releasesGrouped'] = group_releases(releases)

    # Get current week info
    current_week = get_week_key()

    return success_response({
        'email': email,
        'weeks': weeks,
        'count': len(weeks),
        'currentWeek': current_week,
        'currentWeekDisplay': format_week_display(current_week)
    })
