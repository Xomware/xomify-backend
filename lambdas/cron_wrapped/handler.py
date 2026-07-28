"""
Cron: Monthly Wrapped Generation
Runs on the 1st of each month to generate wrapped playlists
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.cron_runs_dynamo import record_cron_run
from lambdas.common.utility_helpers import success_response
from monthly_wrapped_aiohttp import aiohttp_wrapped_chron_job

log = get_logger(__file__)

HANDLER = 'cron_wrapped'
CRON_NAME = 'wrapped'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("🎵 Starting monthly wrapped cron job...")

    stats: dict = {}

    def _wrapped():
        successes, failures = asyncio.run(aiohttp_wrapped_chron_job(event))
        stats["items"] = len(successes) + len(failures)
        return success_response({
            "successfulUsers": successes,
            "failedUsers": failures
        }, is_api=False)

    return record_cron_run(CRON_NAME, _wrapped, items=lambda: stats.get("items"))
