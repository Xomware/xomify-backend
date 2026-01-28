"""
POST /ratings/publish - Create/Update user's track rating for single track
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.track_ratings_dynamo import upsert_track_rating

log = get_logger(__file__)

HANDLER = 'ratings_publish'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'trackId', 'rating', 'trackName', 'artistName', 'albumArt')

    email = body.get('email')
    track_id = body.get('trackId')
    rating = body.get('rating')
    track_name = body.get('trackName')
    artist_name = body.get('artistName')
    album_art = body.get('albumArt')
    album_name = body.get('album_name', None)
    context = body.get('contetxt', None)                  

    log.info(f"Creating/Updating Single Track Rating for user {email} and track id {track_id} with rating {rating}")
    rating = upsert_track_rating(email, track_id, rating, track_name, artist_name, album_art, album_name, context)

    return success_response({
        'rating': rating,
    })
