"""
GET /wrapped/year - Get all wrapped data for a specific year
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.wrapped_data import get_wrapped_year

log = get_logger(__file__)

HANDLER = 'wrapped_year'


@handle_errors(HANDLER)
def handler(event: dict, context: object) -> dict:
    params = get_query_params(event)
    require_fields(params, 'year')

    email: str = get_caller_email(event)
    year: str = params.get('year')

    wraps = get_wrapped_year(email, year)

    return success_response({
        'email': email,
        'year': year,
        'wraps': wraps,
        'count': len(wraps)
    })
