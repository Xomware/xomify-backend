"""
GET /friends/release-radar?email=<friend>[&limit=] - A friend's Release Radar.

Gated on an accepted friendship AND the subject's `releaseRadar` visibility.
Both failures return the same 403.
"""

from lambdas.common.errors import handle_errors
from lambdas.common.friend_visibility_gate import assert_can_read
from lambdas.common.logger import get_logger
from lambdas.common.release_radar_dynamo import get_user_release_radar_history
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    success_response,
)

log = get_logger(__file__)

HANDLER = "friends_release_radar"

# One week is the preview; the screen asks for more when it opens the detail.
DEFAULT_LIMIT = 1
MAX_LIMIT = 12


@handle_errors(HANDLER)
def handler(event, context):
    caller_email = get_caller_email(event)
    params = get_query_params(event) or {}
    subject_email = params.get("email")

    assert_can_read(caller_email, subject_email, "releaseRadar", HANDLER)

    try:
        limit = min(int(params.get("limit", DEFAULT_LIMIT)), MAX_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    log.info(f"{caller_email} reading release radar for {subject_email} (limit={limit})")
    return success_response({
        "email": subject_email,
        "weeks": get_user_release_radar_history(subject_email, limit=limit),
    })
