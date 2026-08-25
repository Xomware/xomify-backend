"""
XOMIFY Notifications Inbox
==========================
Per-user notification feed with read state.

Table: xomify-notifications
- PK  `email` [S]
- SK  `tsId`  [S]  — "<iso8601 ts>#<rand8>"
- attrs: kind, title, body, route, actorEmail, actorName, imageUrl,
         read (bool), createdAt (ISO), ttl (epoch, 90 days)

WHY NOT REUSE xomify-notification-log: that table is PK `day`, read by full
scan, and exists to answer "what did we send yesterday?" for the admin view. A
per-user inbox needs the opposite access pattern — one user's items, newest
first, cheaply, with mutable read state. Bolting a GSA on `toEmail` onto a
send-log would give a send-log with an index, not an inbox. Both tables stay.

The SK sorts lexicographically, and ISO8601 sorts chronologically, so a
descending query IS newest-first with no sort key gymnastics. The `#<rand8>`
suffix only exists to keep two notifications written in the same millisecond
from colliding.

FAIL-OPEN, like everything else on this path: a failed inbox write must not
stop the push going out. Callers get False, not an exception.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.constants import AWS_DEFAULT_REGION
from lambdas.common.logger import get_logger

log = get_logger(__file__)

NOTIFICATIONS_TABLE_NAME = os.environ.get("NOTIFICATIONS_TABLE_NAME", "")

RETENTION_DAYS = 90
#: Hard ceiling on one page. Guards against a client asking for everything.
MAX_PAGE = 50
DEFAULT_PAGE = 25
#: Cap on a mark-all sweep. Beyond this the client should page and re-call —
#: an unbounded update loop in a lambda is how you find the 15-minute timeout.
MAX_MARK_ALL = 300

_dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def _table():
    if not NOTIFICATIONS_TABLE_NAME:
        return None
    return _dynamodb.Table(NOTIFICATIONS_TABLE_NAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch() -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)).timestamp())


def build_ts_id(created_at: Optional[str] = None) -> str:
    return f"{created_at or _now_iso()}#{uuid.uuid4().hex[:8]}"


def put_notification(
    *,
    email: str,
    kind: str,
    title: str,
    body: str,
    route: Optional[str] = None,
    actor_email: Optional[str] = None,
    actor_name: Optional[str] = None,
    image_url: Optional[str] = None,
) -> bool:
    """Write one inbox row. Returns False on failure rather than raising."""
    table = _table()
    if table is None:
        log.warning("NOTIFICATIONS_TABLE_NAME unset — inbox write skipped")
        return False
    if not email:
        return False

    created_at = _now_iso()
    item: dict[str, Any] = {
        "email": email,
        "tsId": build_ts_id(created_at),
        "kind": kind,
        "title": title,
        "body": body,
        "read": False,
        "createdAt": created_at,
        "ttl": _ttl_epoch(),
    }
    for key, value in (
        ("route", route),
        ("actorEmail", actor_email),
        ("actorName", actor_name),
        ("imageUrl", image_url),
    ):
        if value:
            item[key] = value

    try:
        table.put_item(Item=item)
        return True
    except Exception as err:  # noqa: BLE001 — fail-open
        log.error(f"inbox write failed for {email}: {err}")
        return False


def list_notifications(
    email: str,
    limit: int = DEFAULT_PAGE,
    cursor: Optional[str] = None,
) -> dict[str, Any]:
    """
    One page of a user's inbox, newest first.

    `cursor` is the `tsId` of the last item the client already has. Because the
    SK is the sort key and it is time-ordered, paging is a plain
    `ExclusiveStartKey` — no filtering, no scanning past what was returned.
    """
    table = _table()
    if table is None:
        return {"items": [], "nextCursor": None}

    limit = max(1, min(int(limit or DEFAULT_PAGE), MAX_PAGE))

    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("email").eq(email),
        "ScanIndexForward": False,   # newest first
        "Limit": limit,
    }
    if cursor:
        kwargs["ExclusiveStartKey"] = {"email": email, "tsId": cursor}

    try:
        response = table.query(**kwargs)
    except Exception as err:  # noqa: BLE001
        log.error(f"inbox query failed for {email}: {err}")
        return {"items": [], "nextCursor": None}

    items = response.get("Items", [])
    last_key = response.get("LastEvaluatedKey")
    return {
        "items": items,
        "nextCursor": last_key.get("tsId") if last_key else None,
    }


def count_unread(email: str) -> int:
    """
    Unread count for the badge.

    Uses `Select=COUNT` with a filter, so nothing is transferred back — but note
    a filter is applied AFTER the read, so this still reads the partition. At
    90-day retention and one user's traffic that is cheap; if it ever stops
    being cheap, the fix is a sparse GSI keyed on unread items, not a bigger
    page size.
    """
    table = _table()
    if table is None:
        return 0

    total = 0
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("email").eq(email),
        "FilterExpression": "#r = :false",
        "ExpressionAttributeNames": {"#r": "read"},
        "ExpressionAttributeValues": {":false": False},
        "Select": "COUNT",
    }

    try:
        while True:
            response = table.query(**kwargs)
            total += int(response.get("Count", 0))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
    except Exception as err:  # noqa: BLE001
        log.error(f"unread count failed for {email}: {err}")
        return total

    return total


def mark_read(email: str, ts_id: str) -> bool:
    """Mark one item read. Idempotent."""
    table = _table()
    if table is None or not ts_id:
        return False
    try:
        table.update_item(
            Key={"email": email, "tsId": ts_id},
            UpdateExpression="SET #r = :true",
            ExpressionAttributeNames={"#r": "read"},
            ExpressionAttributeValues={":true": True},
            # Do not resurrect a row that TTL already reaped.
            ConditionExpression="attribute_exists(tsId)",
        )
        return True
    except Exception as err:  # noqa: BLE001
        log.warning(f"mark_read failed for {email}/{ts_id}: {err}")
        return False


def mark_all_read(email: str) -> int:
    """
    Mark every unread item read. Returns how many were updated.

    Bounded by MAX_MARK_ALL: an unbounded update loop is how a lambda finds its
    timeout. A user with more than that many unread items marks the rest on a
    second call, which is a far better failure mode than a half-finished sweep
    that reports success.
    """
    table = _table()
    if table is None:
        return 0

    updated = 0
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": Key("email").eq(email),
        "FilterExpression": "#r = :false",
        "ExpressionAttributeNames": {"#r": "read"},
        "ExpressionAttributeValues": {":false": False},
        "ProjectionExpression": "tsId",
    }

    try:
        while updated < MAX_MARK_ALL:
            response = table.query(**kwargs)
            for row in response.get("Items", []):
                if updated >= MAX_MARK_ALL:
                    break
                if mark_read(email, row.get("tsId", "")):
                    updated += 1
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
    except Exception as err:  # noqa: BLE001
        log.error(f"mark_all_read failed for {email}: {err}")

    return updated
