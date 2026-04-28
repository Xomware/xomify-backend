"""
POST /ratings/publish - Create/Update caller's track rating for single track
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.track_ratings_dynamo import upsert_track_rating

log = get_logger(__file__)

HANDLER = 'ratings_publish'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'trackId', 'rating', 'trackName', 'artistName', 'albumArt')

    email: str = get_caller_email(event)
    track_id = body.get('trackId')
    rating = body.get('rating')
    track_name = body.get('trackName')
    artist_name = body.get('artistName')
    album_art = body.get('albumArt')
    album_name = body.get('album_name', None)
    rating_context = body.get('context', None)

    log.info(f"Creating/Updating Single Track Rating for user {email} and track id {track_id} with rating {rating}")
    rating = upsert_track_rating(email, track_id, rating, track_name, artist_name, album_art, album_name, rating_context)

    return success_response({
        'rating': rating,
    })
