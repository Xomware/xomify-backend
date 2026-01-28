"""
GET /user/data - Get user data
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.dynamo_helpers import get_user_table_data

log = get_logger(__file__)

HANDLER = 'user_data'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    response = get_user_table_data(params['email'])
    log.info(f"Retrieved data for {params['email']}")

    return success_response(response)
