"""
POST /visits/log - Record a page-visit for the caller (any authed user).

Body: {"path": "/home"}
Response: {"logged": true, "path": "/home"}

The frontend fires this on route change (throttled). Keyed by the caller's
resolved email; the path is stored verbatim (trimmed, length-capped).
"""

from lambdas.common.errors import ValidationError, handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)
from lambdas.common.visits_dynamo import put_visit

log = get_logger(__file__)

HANDLER = "visits_log"

_MAX_PATH_LEN = 512


@handle_errors(HANDLER)
def handler(event, context):
    email = get_caller_email(event)
    body = parse_body(event)

    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValidationError("path is required", handler=HANDLER, field="path")

    path = path.strip()[:_MAX_PATH_LEN]
    put_visit(email, path)

    log.info(f"visits_log email={email} path={path}")
    return success_response({"logged": True, "path": path})
