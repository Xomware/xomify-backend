"""
Cron: Rate Reminder

Runs daily. One nudge, roughly 24 hours after a share lands, to people who have
neither played it nor rated it.

ONCE PER SHARE, EVER (relaunch epic, decision 9). Latched via `rateRemindedAt`
on the share row using the same conditional write `mark_threshold_notified`
uses, so an overlapping run cannot double-remind. If 24 hours did not get
someone to listen, a second nudge only teaches them to ignore the app.

Flow:
    1. Scan shares whose createdAt falls in the [24h, 48h) window. The lower
       bound gives the share a day to land; the upper bound keeps a daily run
       from re-examining the entire table forever.
    2. Skip anything already latched.
    3. For each of the author's accepted friends who has not listened and has
       not rated, send `rate_reminder`.
    4. Latch the share.

Returns: {"examined": n, "reminded": m, "skipped": s}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from lambdas.common.cron_runs_dynamo import record_cron_run
from lambdas.common.errors import handle_errors
from lambdas.common.interactions_dynamo import list_interactions_for_share
from lambdas.common.logger import get_logger
from lambdas.common.notify import display_name_for, notify
from lambdas.common.share_listeners_dynamo import list_listeners_for_share
from lambdas.common.shares_dynamo import mark_rate_reminded, scan_all_shares
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "cron_rate_reminder"
CRON_NAME = "rate-reminder"

REMIND_AFTER_HOURS = 24
#: Upper bound on the window. A share older than this was either already
#: reminded or missed its moment; re-examining it every day forever is a scan
#: that only grows.
WINDOW_CLOSES_HOURS = 48

#: Ceiling per run, so one pathological day degrades into several runs rather
#: than one timeout that sends nothing.
MAX_REMINDERS_PER_RUN = 200


def _in_window(created_at: str, now: datetime) -> bool:
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = now - created
    return timedelta(hours=REMIND_AFTER_HOURS) <= age < timedelta(hours=WINDOW_CLOSES_HOURS)


def _engaged_emails(share_id: str) -> set[str]:
    """Everyone who has already played or rated this share."""
    engaged: set[str] = set()
    try:
        for row in list_listeners_for_share(share_id) or []:
            if row.get("email"):
                engaged.add(row["email"])
    except Exception as err:  # noqa: BLE001
        log.warning(f"listeners lookup failed for {share_id}: {err}")
    try:
        for row in list_interactions_for_share(share_id) or []:
            # Either signal counts — a rating without a recorded listen still
            # means they engaged, and nudging them would be plainly wrong.
            if row.get("email") and (row.get("queued") or row.get("rated")):
                engaged.add(row["email"])
    except Exception as err:  # noqa: BLE001
        log.warning(f"interactions lookup failed for {share_id}: {err}")
    return engaged


def _audience(author_email: str) -> list[str]:
    from lambdas.common.friendships_dynamo import list_all_friends_for_user

    try:
        rows = list_all_friends_for_user(author_email) or []
    except Exception as err:  # noqa: BLE001
        log.warning(f"friends lookup failed for {author_email}: {err}")
        return []
    return [
        r["friendEmail"]
        for r in rows
        if isinstance(r, dict)
        and r.get("status") == "accepted"
        and r.get("friendEmail")
        and r["friendEmail"] != author_email
    ]


def _run() -> dict:
    now = datetime.now(timezone.utc)
    examined = 0
    reminded = 0
    skipped = 0

    for page in scan_all_shares(page_size=100):
        for share in page:
            if reminded >= MAX_REMINDERS_PER_RUN:
                log.warning(f"rate reminder run capped at {MAX_REMINDERS_PER_RUN}")
                return {"examined": examined, "reminded": reminded, "skipped": skipped}

            if not _in_window(share.get("createdAt", ""), now):
                continue
            examined += 1

            share_id = share.get("shareId")
            author = share.get("email") or share.get("sharedBy")
            if not share_id or not author:
                skipped += 1
                continue

            # Latch FIRST. Losing the race means another run owns this share;
            # doing the work and then discovering that would waste the reads.
            if not mark_rate_reminded(share_id):
                skipped += 1
                continue

            engaged = _engaged_emails(share_id)
            actor_name = display_name_for(author)

            for recipient in _audience(author):
                if recipient in engaged:
                    continue
                notify(
                    "rate_reminder",
                    recipient,
                    actor_email=author,
                    actor_name=actor_name,
                    track_name=share.get("trackName") or "that track",
                    artist_name=share.get("artistName"),
                    share_id=share_id,
                )
                reminded += 1

    return {"examined": examined, "reminded": reminded, "skipped": skipped}


@handle_errors(HANDLER)
def handler(event, context):
    stats: dict = {}

    def _wrapped():
        stats.update(_run())
        log.info(f"rate reminder: {stats}")
        return success_response(stats, is_api=False)

    return record_cron_run(CRON_NAME, _wrapped, items=lambda: stats.get("reminded"))
