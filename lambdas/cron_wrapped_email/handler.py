"""
Cron: Monthly Wrapped Email
Sends email notifications for monthly wrapped
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from monthly_wrapped_email import wrapped_email_cron_job

log = get_logger(__file__)

HANDLER = 'cron_wrapped_email'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("📧 Starting monthly wrapped email cron job...")

    successes, failures = asyncio.run(wrapped_email_cron_job(event))

    return success_response({
        "successfulEmails": successes,
        "failedEmails": failures
    }, is_api=False)
