"""
Cron: Year-end favorites reminder.

Scans the users table and emails every active user a "Set your {year} favorites"
reminder. Idempotent per user per year via a REMINDER#{year} marker in the
favorites table, so re-running the cron never double-sends.

Response (is_api=False): {successfulEmails, failedEmails, skipped}

Assumption: targets users with `active == True` — there is no separate
favorites-enrollment flag.
"""

from datetime import datetime, timezone

from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.cron_runs_dynamo import record_cron_run
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.errors import handle_errors
from lambdas.common.favorites_dynamo import get_reminder_marker, put_reminder_marker
from lambdas.common.logger import get_logger
from lambdas.common.ses_helper import send_favorites_reminder_email
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "cron_favorites_reminder"
CRON_NAME = "favorites-reminder"


def _run():
    year = datetime.now(timezone.utc).year
    log.info(f"🎧 Starting favorites reminder cron for {year}...")

    users = full_table_scan(USERS_TABLE_NAME)

    successful = 0
    failed = 0
    skipped = 0

    for user in users:
        if not user.get("active"):
            continue

        email = user.get("email")
        if not email:
            continue

        if get_reminder_marker(email, year):
            log.info(f"favorites reminder already sent email={email} year={year}")
            skipped += 1
            continue

        try:
            send_favorites_reminder_email(email, user.get("displayName") or "", year)
            put_reminder_marker(email, year)
            successful += 1
        except Exception as err:  # noqa: BLE001 - isolate per-user send failures
            log.error(f"favorites reminder send failed email={email}: {err}")
            failed += 1

    log.info(
        f"favorites reminder cron done year={year} "
        f"sent={successful} failed={failed} skipped={skipped}"
    )

    return successful, failed, skipped


@handle_errors(HANDLER)
def handler(event, context):
    stats: dict = {}

    def _wrapped():
        successful, failed, skipped = _run()
        stats["items"] = successful + failed + skipped
        return success_response({
            "successfulEmails": successful,
            "failedEmails": failed,
            "skipped": skipped,
        }, is_api=False)

    return record_cron_run(CRON_NAME, _wrapped, items=lambda: stats.get("items"))
