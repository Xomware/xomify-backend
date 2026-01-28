"""
Cron: Weekly Release Radar Generation
Runs on Saturday morning to generate release radar playlists
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from weekly_release_radar_aiohttp import release_radar_cron_job

log = get_logger(__file__)

HANDLER = 'cron_release_radar'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("📻 Starting weekly release radar cron job...")

    successes, failures = asyncio.run(release_radar_cron_job(event))

    return success_response({
        "successfulUsers": successes,
        "failedUsers": failures
    }, is_api=False)
