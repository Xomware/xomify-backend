"""
GET /wrapped/all - Get user's wrapped data and history
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_caller_email
from lambdas.common.wrapped_data import get_wrapped_data

log = get_logger(__file__)

HANDLER = 'wrapped_all'


@handle_errors(HANDLER)
def handler(event: dict, context: object) -> dict:
    email: str = get_caller_email(event)
    data = get_wrapped_data(email)

    return success_response(data)
