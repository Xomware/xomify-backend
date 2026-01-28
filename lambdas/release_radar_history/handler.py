"""
GET /release-radar/history - Get user's release radar history
"""

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.release_radar_dynamo import (
    get_user_release_radar_history,
    get_week_key,
    format_week_display
)

log = get_logger(__file__)

HANDLER = 'release_radar_history'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email')

    email = params.get('email')
    limit = int(params.get('limit', 26))

    weeks = get_user_release_radar_history(email, limit=limit)

    # Add display name to each week
    for week in weeks:
        week['weekDisplay'] = format_week_display(week.get('weekKey', ''))

    # Get current week info
    current_week = get_week_key()

    return success_response({
        'email': email,
        'weeks': weeks,
        'count': len(weeks),
        'currentWeek': current_week,
        'currentWeekDisplay': format_week_display(current_week)
    })
