"""
Cron: Weekly Release Radar Email
Sends email notifications for weekly release radar
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from weekly_release_radar_email import release_radar_email_cron_job

log = get_logger(__file__)

HANDLER = 'cron_release_radar_email'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("📧 Starting weekly release radar email cron job...")

    successes, failures, skipped = asyncio.run(release_radar_email_cron_job(event))

    return success_response({
        "successfulEmails": successes,
        "failedEmails": failures,
        "skippedEmails": skipped
    }, is_api=False)
