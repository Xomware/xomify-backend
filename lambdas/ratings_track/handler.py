"""
GET /ratings/all - Get user's track rating for single track
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.track_ratings_dynamo import get_single_track_rating_for_user

log = get_logger(__file__)

HANDLER = 'ratings_track'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email', 'trackId')

    email = params.get('email')
    track_id = params.get('trackId')

    log.info(f"Getting Single Track Rating for user {email} and track id {track_id}")
    rating = get_single_track_rating_for_user(email, track_id)

    return success_response({
        'rating': rating,
    })
