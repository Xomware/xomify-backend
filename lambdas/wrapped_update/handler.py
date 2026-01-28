"""
POST /wrapped/update - Update user's wrapped enrollment
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.wrapped_data import update_wrapped_data

log = get_logger(__file__)

HANDLER = 'wrapped_update'


@handle_errors(HANDLER)
def handler(event, context):
    body = parse_body(event)
    require_fields(body, 'email', 'userId', 'refreshToken', 'active')

    message = update_wrapped_data(body)

    return success_response({'message': message})
