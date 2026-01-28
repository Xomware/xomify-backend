"""
Cron: Monthly Wrapped Generation
Runs on the 1st of each month to generate wrapped playlists
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response

# Import cron job from wrapped module
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'wrapped'))
from monthly_wrapped_aiohttp import wrapped_cron_job

log = get_logger(__file__)

HANDLER = 'cron_wrapped'


@handle_errors(HANDLER)
def handler(event, context):
    log.info("🎵 Starting monthly wrapped cron job...")

    successes, failures = asyncio.run(wrapped_cron_job(event))

    return success_response({
        "successfulUsers": successes,
        "failedUsers": failures
    }, is_api=False)
