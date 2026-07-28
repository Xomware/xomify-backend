"""
XOMIFY Notification Log DynamoDB Helpers
========================================
Backs the admin Notifications sub-tab. Every outbound email (SES) and push
(APNs) send records a row here.

Table: xomify-notification-log
- PK  `day`  [S]  — "YYYY-MM-DD" (UTC) partition
- SK  `tsId` [S]  — "<iso8601 ts>#<rand8>"
- attrs: ts(ISO), channel("email"|"push"), toEmail, subject,
         bodyPreview(<=200 chars), status("sent"|"failed"), error?(str)

`record_notification(...)` is FAIL-OPEN — logging a send must never break the
actual send path. Reads (admin Notifications) scan the table and sort desc.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import boto3

from lambdas.common.constants import AWS_DEFAULT_REGION, NOTIFICATION_LOG_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)

BODY_PREVIEW_MAX = 200


def record_notification(
    *,
    channel: str,
    to_email: str,
    subject: str,
    body_preview: str,
    status: str,
    error: str | None = None,
) -> None:
    """Append one notification-log row. Fail-open — never raises."""
    if not NOTIFICATION_LOG_TABLE_NAME:
        return
    try:
        now = datetime.now(timezone.utc)
        ts = now.isoformat()
        item = {
            "day": now.strftime("%Y-%m-%d"),
            "tsId": f"{ts}#{uuid.uuid4().hex[:8]}",
            "ts": ts,
            "channel": channel,
            "toEmail": to_email or "",
            "subject": (subject or "")[:200],
            "bodyPreview": (body_preview or "")[:BODY_PREVIEW_MAX],
            "status": status,
        }
        if error:
            item["error"] = str(error)[:500]
        dynamodb.Table(NOTIFICATION_LOG_TABLE_NAME).put_item(Item=item)
    except Exception as err:  # noqa: BLE001 - instrumentation is best-effort
        log.warning(f"record_notification failed (ignored): {err}")


def list_recent_notifications(limit: int = 100) -> list[dict]:
    """Most-recent-first notification rows, capped at `limit`."""
    if not NOTIFICATION_LOG_TABLE_NAME:
        return []
    rows = full_table_scan(NOTIFICATION_LOG_TABLE_NAME)
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return rows[:limit]
