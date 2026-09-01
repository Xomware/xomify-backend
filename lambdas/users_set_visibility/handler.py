"""
POST /users/visibility - Set which of the caller's artefacts friends can see.

Body (PARTIAL - only the keys present are changed):
    {
        "wrapped":      "friends" | "private",
        "releaseRadar": "friends" | "private",
        "topItems":     "friends" | "private"
    }

Caller identity comes from the authorizer context. There is no `email` in the
body: a settings endpoint that takes the subject as a parameter is the exact
shape the auth-identity epic exists to remove.

Returns the FULL resulting map, not just what changed, so a client never has to
merge its own optimistic state with the response.
"""

from lambdas.common.errors import ValidationError, handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.user_visibility import FIELDS, set_visibility
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = "users_set_visibility"


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    caller_email = get_caller_email(event)

    updates = {key: body[key] for key in FIELDS if key in body}
    if not updates:
        raise ValidationError(
            message=f"Give at least one of: {sorted(FIELDS)}",
            handler=HANDLER,
            function="handler",
        )

    visibility = set_visibility(caller_email, updates)
    return success_response({"email": caller_email, "visibility": visibility})
