"""
Cron: Weekly Release Radar Email
Sends email notifications for weekly release radar
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response

# Import email function from release_radar_email module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'release_radar_email'))
from weekly_release_radar_email import weekly_release_radar_email

log = get_logger(__file__)

HANDLER = 'cron_release_radar_email'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("📧 Starting weekly release radar email cron job...")

    successes, failures = asyncio.run(weekly_release_radar_email(event))

    return success_response({
        "successfulEmails": successes,
        "failedEmails": failures
    }, is_api=False)
