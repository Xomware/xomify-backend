"""
XOMIFY Request Log DynamoDB Helpers
===================================
Backs the admin Health sub-tab.

Table: xomify-request-log
- PK  `day`  [S]  — "YYYY-MM-DD" (UTC) partition, keeps writes spread across days
- SK  `tsId` [S]  — "<iso8601 ts>#<rand8>" (lexicographically sortable by time)
- attrs: ts(ISO), path, method, status(int), email, error?(str),
         durationMs(int), ttl(epoch int, ~14d)

Writes are FAIL-OPEN: instrumentation must never break a real request. Reads
(admin Health) walk the day partitions covering the requested window and query
each with a `tsId >= cutoff` condition.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.constants import (
    AWS_DEFAULT_REGION,
    REQUEST_LOG_TABLE_NAME,
    REQUEST_LOG_TTL_DAYS,
    USERS_TABLE_NAME,
)
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_key(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def record_request(
    *,
    path: str,
    method: str,
    status: int,
    email: str | None,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Append one request-log row. Fail-open — never raises."""
    if not REQUEST_LOG_TABLE_NAME:
        return
    try:
        now = _now()
        ts = now.isoformat()
        item = {
            "day": _day_key(now),
            "tsId": f"{ts}#{uuid.uuid4().hex[:8]}",
            "ts": ts,
            "path": path or "unknown",
            "method": method or "unknown",
            "status": int(status),
            "email": email or "",
            "durationMs": int(duration_ms),
            "ttl": int((now + timedelta(days=REQUEST_LOG_TTL_DAYS)).timestamp()),
        }
        if error:
            # Cap the stored error so a giant traceback never bloats the row.
            item["error"] = str(error)[:500]
        dynamodb.Table(REQUEST_LOG_TABLE_NAME).put_item(Item=item)
    except Exception as err:  # noqa: BLE001 - instrumentation is best-effort
        log.warning(f"record_request failed (ignored): {err}")


def query_requests_since(cutoff: datetime) -> list[dict]:
    """
    Return every request-log row with ts >= cutoff, across the day partitions
    spanning [cutoff, now]. Small personal-app volume; each day is a bounded
    Query, not a table scan.
    """
    if not REQUEST_LOG_TABLE_NAME:
        return []
    table = dynamodb.Table(REQUEST_LOG_TABLE_NAME)
    cutoff_iso = cutoff.isoformat()
    rows: list[dict] = []

    day = cutoff.date()
    today = _now().date()
    while day <= today:
        day_str = day.strftime("%Y-%m-%d")
        try:
            resp = table.query(
                KeyConditionExpression=Key("day").eq(day_str)
                & Key("tsId").gte(cutoff_iso),
            )
            rows.extend(resp.get("Items", []))
            while "LastEvaluatedKey" in resp:
                resp = table.query(
                    KeyConditionExpression=Key("day").eq(day_str)
                    & Key("tsId").gte(cutoff_iso),
                    ExclusiveStartKey=resp["LastEvaluatedKey"],
                )
                rows.extend(resp.get("Items", []))
        except Exception as err:  # noqa: BLE001 - one bad partition shouldn't 500 admin
            log.warning(f"query_requests_since day={day_str} failed: {err}")
        day += timedelta(days=1)

    return rows


def upsert_last_seen(email: str) -> None:
    """
    Stamp `lastSeen` on the existing users row for `email`. Fail-open and
    conditional on the row already existing, so instrumentation never creates
    phantom user rows for unknown identities.
    """
    if not email or not USERS_TABLE_NAME:
        return
    try:
        dynamodb.Table(USERS_TABLE_NAME).update_item(
            Key={"email": email},
            UpdateExpression="SET lastSeen = :ts",
            ConditionExpression="attribute_exists(email)",
            ExpressionAttributeValues={":ts": _now().isoformat()},
        )
    except Exception as err:  # noqa: BLE001 - includes ConditionalCheckFailed
        log.debug(f"upsert_last_seen skipped for {email}: {err}")
