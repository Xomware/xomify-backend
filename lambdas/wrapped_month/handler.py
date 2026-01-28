"""
GET /wrapped/month - Get specific month's wrapped data
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors, NotFoundError
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.wrapped_data import get_wrapped_month

log = get_logger(__file__)

HANDLER = 'wrapped_month'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email', 'monthKey')

    email = params.get('email')
    month_key = params.get('monthKey')

    wrap = get_wrapped_month(email, month_key)

    if not wrap:
        raise NotFoundError(
            message=f"No wrapped data found for {month_key}",
            handler=HANDLER,
            function="handler",
            resource=f"{email}/{month_key}"
        )

    return success_response(wrap)
