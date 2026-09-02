"""
GET /friends/wrapped?email=<friend> - A friend's Wrapped archive.

Same payload the owner sees from /wrapped/all. What differs is the door: the
caller must be an accepted friend AND the subject's `wrapped` visibility must
be `friends`. Both failures return the same 403, so this cannot be used to
probe who has it enabled.
"""

from lambdas.common.errors import handle_errors
from lambdas.common.friend_visibility_gate import assert_can_read
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    success_response,
)
from lambdas.common.wrapped_data import get_wrapped_data

log = get_logger(__file__)

HANDLER = "friends_wrapped"


@handle_errors(HANDLER)
def handler(event, context):
    caller_email = get_caller_email(event)
    subject_email = (get_query_params(event) or {}).get("email")

    assert_can_read(caller_email, subject_email, "wrapped", HANDLER)

    log.info(f"{caller_email} reading wrapped for {subject_email}")
    return success_response({
        "email": subject_email,
        "wrapped": get_wrapped_data(subject_email),
    })
