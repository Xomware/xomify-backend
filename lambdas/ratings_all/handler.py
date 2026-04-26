"""
GET /ratings/all - Get all of the caller's track ratings
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_caller_email
from lambdas.common.track_ratings_dynamo import list_all_track_ratings_for_user

log = get_logger(__file__)

HANDLER = 'ratings_all'


@handle_errors(HANDLER)
def handler(event, context):
    email: str = get_caller_email(event)

    log.info(f"Getting all Track Ratings for user {email}")
    ratings = list_all_track_ratings_for_user(email)

    return success_response({
        'ratings': ratings,
        'totalRatings': len(ratings)
    })
