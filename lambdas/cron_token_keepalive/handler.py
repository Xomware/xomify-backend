"""
Cron: Monthly Token Keepalive
Runs on the 15th of each month to refresh all user tokens,
preventing Spotify from revoking them due to inactivity.
"""

import asyncio
import aiohttp
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.spotify import Spotify

log = get_logger(__file__)

HANDLER = 'cron_token_keepalive'


async def refresh_user_token(user: dict, session: aiohttp.ClientSession) -> dict:
    """Refresh a single user's Spotify token."""
    email = user.get('email', 'unknown')
    try:
        spotify = Spotify(user, session)
        await spotify.aiohttp_get_access_token()
        log.info(f"{email}: Token refreshed successfully")
        return {"email": email, "status": "success"}
    except Exception as err:
        error_msg = str(err)
        log.error(f"{email}: Token refresh failed - {error_msg}")

        # Check if token is revoked
        is_revoked = 'invalid_grant' in error_msg.lower()
        return {
            "email": email,
            "status": "revoked" if is_revoked else "error",
            "error": error_msg
        }


async def keepalive_all_tokens(event: dict) -> tuple[list, list]:
    """Refresh tokens for all users to keep them active."""
    log.info("Starting monthly token keepalive...")

    all_users = full_table_scan(USERS_TABLE_NAME)
    # Only refresh tokens for active users with refresh tokens
    users = [u for u in all_users if u.get('active', False) and u.get('refreshToken')]
    log.info(f"Found {len(users)} users to process")

    successes = []
    failures = []

    async with aiohttp.ClientSession() as session:
        tasks = [refresh_user_token(user, session) for user in users]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                failures.append({"email": "unknown", "error": str(result)})
            elif result.get("status") == "success":
                successes.append(result["email"])
            else:
                failures.append(result)

    log.info(f"Token keepalive complete: {len(successes)} refreshed, {len(failures)} failed")

    # Log failures with details
    for failure in failures:
        status = failure.get("status", "error")
        if status == "revoked":
            log.warning(f"REVOKED TOKEN: {failure['email']} - needs to re-login")
        else:
            log.error(f"FAILED: {failure['email']} - {failure.get('error', 'unknown')}")

    return successes, failures


@handle_errors(HANDLER)
def handler(event, context):
    log.info("Starting monthly token keepalive cron job...")

    successes, failures = asyncio.run(keepalive_all_tokens(event))

    return success_response({
        "refreshedUsers": successes,
        "failedUsers": failures,
        "summary": {
            "total": len(successes) + len(failures),
            "refreshed": len(successes),
            "failed": len(failures)
        }
    }, is_api=False)
