"""
Cron: Monthly Wrapped Email
Sends email notifications for monthly wrapped
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.cron_runs_dynamo import record_cron_run
from lambdas.common.utility_helpers import success_response
from monthly_wrapped_email import wrapped_email_cron_job

log = get_logger(__file__)

HANDLER = 'cron_wrapped_email'
CRON_NAME = 'wrapped-email'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("📧 Starting monthly wrapped email cron job...")

    stats: dict = {}

    def _wrapped():
        successes, failures = asyncio.run(wrapped_email_cron_job(event))
        stats["items"] = len(successes) + len(failures)
        return success_response({
            "successfulEmails": successes,
            "failedEmails": failures
        }, is_api=False)

    return record_cron_run(CRON_NAME, _wrapped, items=lambda: stats.get("items"))
