"""
GET /release-radar/check - Check user's release radar enrollment status
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_caller_email
from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.release_radar_dynamo import (
    check_user_has_history,
    get_week_key,
    get_week_date_range,
    format_week_display
)

log = get_logger(__file__)

HANDLER = 'release_radar_check'


@handle_errors(HANDLER)
def handler(event: dict, context) -> dict:
    email: str = get_caller_email(event)

    has_history = check_user_has_history(email)
    current_week = get_week_key()
    start_date, end_date = get_week_date_range(current_week)

    # Check if user is enrolled
    user = get_user_table_data(email)
    is_enrolled = user.get('activeReleaseRadar', False) if user else False

    return success_response({
        'email': email,
        'enrolled': is_enrolled,
        'hasHistory': has_history,
        'currentWeek': current_week,
        'currentWeekDisplay': format_week_display(current_week),
        'weekStartDate': start_date.strftime('%Y-%m-%d'),
        'weekEndDate': end_date.strftime('%Y-%m-%d')
    })
