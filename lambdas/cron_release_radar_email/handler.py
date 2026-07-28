"""
Cron: Weekly Release Radar Email
Sends email notifications for weekly release radar
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.cron_runs_dynamo import record_cron_run
from lambdas.common.utility_helpers import success_response
from weekly_release_radar_email import release_radar_email_cron_job

log = get_logger(__file__)

HANDLER = 'cron_release_radar_email'
CRON_NAME = 'release-radar-email'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("📧 Starting weekly release radar email cron job...")

    stats: dict = {}

    def _wrapped():
        successes, failures, skipped = asyncio.run(release_radar_email_cron_job(event))
        stats["items"] = len(successes) + len(failures) + len(skipped)
        return success_response({
            "successfulEmails": successes,
            "failedEmails": failures,
            "skippedEmails": skipped
        }, is_api=False)

    return record_cron_run(CRON_NAME, _wrapped, items=lambda: stats.get("items"))
