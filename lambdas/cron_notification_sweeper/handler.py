"""
Cron: Notification Coalescing Sweeper

Scheduled via EventBridge every 5 minutes.

Coalescing (relaunch epic, decision 11) parks the first of a pair of sibling
notifications — share_listened / share_rated — for up to 10 minutes, hoping its
partner arrives so the two can go out as one push. When the partner never comes,
something has to send the parked one on its own. That is this.

WHY IT CANNOT RIDE THE DAILY cron_rate_reminder SCHEDULE: the coalesce window is
ten minutes. A daily sweeper would hold a lone "Sam listened to your song" for
up to twenty-four hours, which is worse than never sending it.

Flow:
    1. Claim every pending row whose window has lapsed (delete-on-take, so two
       overlapping runs cannot both send the same one).
    2. Dispatch each with its own wording — a listen with no rating is just a
       listen, not "listened and rated".

Returns: {"swept": n, "failed": m}
"""

from __future__ import annotations

from lambdas.common.cron_runs_dynamo import record_cron_run
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.notification_pending_dynamo import take_expired
from lambdas.common.notify import dispatch_pending
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "cron_notification_sweeper"
CRON_NAME = "notification-sweeper"

#: One run's ceiling. At a 5-minute cadence this is far above any realistic
#: backlog; it exists so a pathological pile-up degrades into several runs
#: rather than one timing out and sending nothing at all.
MAX_PER_RUN = 200


@handle_errors(HANDLER)
def handler(event, context):
    rows = take_expired(limit=MAX_PER_RUN)

    swept = 0
    failed = 0

    for row in rows:
        try:
            dispatch_pending(row)
            swept += 1
        except Exception as err:  # noqa: BLE001
            # dispatch_pending is already fail-open; this is belt-and-braces so
            # one bad row cannot strand the rest of the batch.
            log.error(f"sweeper failed to dispatch {row.get('coalesceKey')}: {err}")
            failed += 1

    stats = {"swept": swept, "failed": failed}
    log.info(f"notification sweeper: {stats}")

    record_cron_run(CRON_NAME, stats)
    return success_response(stats, is_api=False)
