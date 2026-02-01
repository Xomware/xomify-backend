"""
Cron: Monthly Wrapped Generation
Runs on the 1st of each month to generate wrapped playlists
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from monthly_wrapped_aiohttp import aiohttp_wrapped_chron_job

log = get_logger(__file__)

HANDLER = 'cron_wrapped'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("🎵 Starting monthly wrapped cron job...")

    successes, failures = asyncio.run(aiohttp_wrapped_chron_job(event))

    return success_response({
        "successfulUsers": successes,
        "failedUsers": failures
    }, is_api=False)
