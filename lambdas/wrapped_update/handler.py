"""
POST /wrapped/update - Update user's wrapped enrollment
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    parse_body,
    require_fields,
    get_caller_email,
)
from lambdas.common.wrapped_data import update_wrapped_data

log = get_logger(__file__)

HANDLER = 'wrapped_update'


@handle_errors(HANDLER)
def handler(event: dict, context: object) -> dict:
    body = parse_body(event)
    require_fields(body, 'userId', 'refreshToken', 'active')

    # Caller email comes from the trusted authorizer context (with query/body
    # fallback during the Track 1 migration window). Overwrites any
    # client-supplied `email` in the body so the persisted row is keyed on the
    # authenticated caller.
    body['email'] = get_caller_email(event)

    message = update_wrapped_data(body)

    return success_response({'message': message})
