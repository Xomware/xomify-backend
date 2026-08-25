"""
XOMIFY Pending (Coalescing) Notifications
=========================================
Backs the coalescing window described in the relaunch epic, decision 11.

Table: xomify-notification-pending
- PK  `coalesceKey` [S]  — "<recipient>#<group>#<subject>"
- attrs: kind, ctx (map), recipientEmail, createdAt (ISO), expiresAt (epoch),
         ttl (epoch, = expiresAt + slack)

WHY A TABLE AND NOT APNs `collapse_id`: collapse-id replaces the notification
already sitting in the tray, which fixes the CLUTTER but not the BUZZ — the
second push still alerts. The whole point of coalescing here is that one act
of engagement (play, then rate) produces one interruption. That requires
holding the first event back, which requires somewhere to hold it.

FAIL-OPEN: every function here returns a sentinel rather than raising. If this
table is unreachable — or not yet provisioned, since B6 lands after B1 — the
caller falls back to dispatching immediately. Losing coalescing is a cosmetic
regression; losing the notification is not.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from lambdas.common.constants import AWS_DEFAULT_REGION
from lambdas.common.logger import get_logger

import os

log = get_logger(__file__)

NOTIFICATION_PENDING_TABLE_NAME = os.environ.get(
    "NOTIFICATION_PENDING_TABLE_NAME", ""
)

#: Grace on top of the coalesce window before DynamoDB TTL reaps the row. The
#: sweeper needs a chance to see an expired row and dispatch it; TTL deletion
#: is only "within 48 hours" anyway, so this is belt-and-braces.
TTL_SLACK_S = 3600

_dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def _table():
    if not NOTIFICATION_PENDING_TABLE_NAME:
        return None
    return _dynamodb.Table(NOTIFICATION_PENDING_TABLE_NAME)


def coalesce_key(recipient_email: str, group: str, subject_id: str) -> str:
    return f"{recipient_email}#{group}#{subject_id}"


def claim_or_merge(
    *,
    key: str,
    kind: str,
    recipient_email: str,
    ctx: dict[str, Any],
    window_s: int,
) -> Optional[dict[str, Any]]:
    """
    Try to park this notification for `window_s`.

    Returns:
        None                     — parked. Caller must NOT dispatch; either the
                                   sibling event merges with it, or the sweeper
                                   sends it once the window lapses.
        {"merged": True, ...}    — a sibling was already parked. The row has
                                   been deleted and the merged context returned;
                                   caller dispatches ONE push covering both.
        {"merged": False, ...}   — coalescing unavailable (no table, or DynamoDB
                                   refused). Caller dispatches immediately.

    The conditional write is what makes two near-simultaneous events safe: only
    one can create the row, so the loser reads it back and merges rather than
    both parking and neither ever sending.
    """
    table = _table()
    if table is None:
        log.warning("NOTIFICATION_PENDING_TABLE_NAME unset — coalescing disabled")
        return {"merged": False, "ctx": ctx, "kinds": [kind]}

    now = int(time.time())
    expires_at = now + window_s

    try:
        table.put_item(
            Item={
                "coalesceKey": key,
                "kind": kind,
                "recipientEmail": recipient_email,
                "ctx": ctx,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "expiresAt": expires_at,
                "ttl": expires_at + TTL_SLACK_S,
            },
            ConditionExpression="attribute_not_exists(coalesceKey)",
        )
        return None
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            log.error(f"coalesce claim failed for {key}: {err} — dispatching uncoalesced")
            return {"merged": False, "ctx": ctx, "kinds": [kind]}

    # Someone got there first. Take the row and merge.
    try:
        existing = table.delete_item(
            Key={"coalesceKey": key},
            ReturnValues="ALL_OLD",
        ).get("Attributes")
    except ClientError as err:
        log.error(f"coalesce merge-delete failed for {key}: {err} — dispatching uncoalesced")
        return {"merged": False, "ctx": ctx, "kinds": [kind]}

    if not existing:
        # Raced with the sweeper, which already sent the parked one. Ours is
        # then a genuine second event and dispatches on its own.
        return {"merged": False, "ctx": ctx, "kinds": [kind]}

    prior_ctx = dict(existing.get("ctx") or {})
    prior_kind = existing.get("kind")
    # The later event's context wins on conflict — a rating arriving after a
    # listen carries the star count, which is the more informative of the two.
    merged_ctx = {**prior_ctx, **ctx}
    return {
        "merged": True,
        "ctx": merged_ctx,
        "kinds": [k for k in (prior_kind, kind) if k],
    }


def take_expired(limit: int = 200) -> list[dict[str, Any]]:
    """
    Claim pending rows whose window has lapsed, for the sweeper to dispatch.

    Each row is deleted as it is taken, so two overlapping sweeper runs cannot
    both send the same notification.
    """
    table = _table()
    if table is None:
        return []

    now = int(time.time())
    taken: list[dict[str, Any]] = []

    try:
        scan_kwargs: dict[str, Any] = {"Limit": limit}
        response = table.scan(**scan_kwargs)
        candidates = [
            item for item in response.get("Items", [])
            if int(item.get("expiresAt", 0)) <= now
        ]
    except ClientError as err:
        log.error(f"pending scan failed: {err}")
        return []

    for item in candidates:
        try:
            claimed = table.delete_item(
                Key={"coalesceKey": item["coalesceKey"]},
                ConditionExpression="attribute_exists(coalesceKey)",
                ReturnValues="ALL_OLD",
            ).get("Attributes")
        except ClientError:
            # Lost the race to another sweeper run — fine, it will send it.
            continue
        if claimed:
            taken.append(claimed)

    return taken
