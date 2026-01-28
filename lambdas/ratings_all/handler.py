"""
GET /ratings/all - Get all user's track ratings
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.track_ratings_dynamo import list_all_track_ratings_for_user

log = get_logger(__file__)

HANDLER = 'ratings_all'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')

    log.info(f"Getting all Track Ratings for user {email}")
    ratings = list_all_track_ratings_for_user(email)

    return success_response({
        'ratings': ratings,
        'totalRatings': len(ratings)
    })
