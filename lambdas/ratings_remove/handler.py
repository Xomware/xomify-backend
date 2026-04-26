"""
DELETE /ratings/remove - Delete caller's track rating for single track
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.track_ratings_dynamo import delete_track_rating

log = get_logger(__file__)

HANDLER = 'ratings_remove'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'trackId')

    email: str = get_caller_email(event)
    track_id = params.get('trackId')

    log.info(f"Deleting Single Track Rating for user {email} and track id {track_id}")
    success = delete_track_rating(email, track_id)

    return success_response({
        'success': success,
    })
