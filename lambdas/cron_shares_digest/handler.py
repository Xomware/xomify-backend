"""
Cron: Weekly Shares Digest

Scheduled via EventBridge (Sunday 18:00 UTC by default). For every user who
has opted into the digest, counts shares authored by their friends in the
prior 7 days and fires a single APNs push summarizing the activity.

Flow:
    1. Scan device-tokens for rows with digestEnabled=true, group by email.
    2. For each email, fetch their accepted-friend emails and count how many
       shares those friends authored in the last 7 days.
    3. Skip users with zero new shares (don't spam empty weeks).
    4. Async-invoke notifications_send for the remaining users.

Returns: {"processed": n, "invoked": m, "skipped": s, "failed": f}
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3

from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response
from lambdas.common.constants import NOTIFICATIONS_SEND_FUNCTION_NAME
from lambdas.common.device_tokens_dynamo import (
    group_tokens_by_email,
    scan_tokens_for_digest,
)
from lambdas.common.friendships_dynamo import list_all_friends_for_user
from lambdas.common.shares_dynamo import list_shares_for_user

log = get_logger(__file__)

HANDLER = "cron_shares_digest"
DIGEST_WINDOW_DAYS = 7

_lambda_client = boto3.client("lambda", region_name="us-east-1")


def _window_cutoff_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=DIGEST_WINDOW_DAYS)).isoformat()


def _count_recent_shares_from_friends(email: str, cutoff_iso: str) -> int:
    """Sum of shares authored by this user's accepted friends in the window."""
    friends = list_all_friends_for_user(email)
    friend_emails = [
        f.get("friendEmail")
        for f in friends
        if f.get("status") == "accepted" and f.get("friendEmail")
    ]
    if not friend_emails:
        return 0

    total = 0
    for friend_email in friend_emails:
        try:
            shares, _ = list_shares_for_user(friend_email, limit=100, before=None)
        except Exception as err:
            log.warning(f"Digest share lookup failed for {friend_email}: {err}")
            continue
        for share in shares:
            created_at = share.get("createdAt", "")
            if created_at >= cutoff_iso:
                total += 1
    return total


def _invoke_digest_push(email: str, count: int) -> None:
    if not NOTIFICATIONS_SEND_FUNCTION_NAME:
        log.warning(
            "NOTIFICATIONS_SEND_FUNCTION_NAME not set — cron cannot dispatch push"
        )
        return
    plural = "share" if count == 1 else "shares"
    event = {
        "kind": "digest",
        "email": email,
        "title": "Your weekly Xomify digest",
        "body": f"{count} new {plural} from your friends this week",
        "customData": {"count": count, "windowDays": DIGEST_WINDOW_DAYS},
    }
    _lambda_client.invoke(
        FunctionName=NOTIFICATIONS_SEND_FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps(event).encode("utf-8"),
    )
    log.info(f"Digest push dispatched to {email} (count={count})")


@handle_errors(HANDLER)
def handler(event, context):
    log.info("Starting weekly shares digest cron")

    tokens = list(scan_tokens_for_digest())
    grouped = group_tokens_by_email(tokens)
    cutoff = _window_cutoff_iso()

    processed = 0
    invoked = 0
    skipped = 0
    failed = 0

    for email in grouped.keys():
        processed += 1
        try:
            count = _count_recent_shares_from_friends(email, cutoff)
        except Exception as err:
            failed += 1
            log.error(f"Digest computation failed for {email}: {err}")
            continue

        if count <= 0:
            skipped += 1
            continue

        try:
            _invoke_digest_push(email, count)
            invoked += 1
        except Exception as err:
            failed += 1
            log.error(f"Digest dispatch failed for {email}: {err}")

    result: dict[str, Any] = {
        "processed": processed,
        "invoked": invoked,
        "skipped": skipped,
        "failed": failed,
        "cutoff": cutoff,
    }
    log.info(f"Weekly digest cron complete: {result}")
    return success_response(result, is_api=False)
