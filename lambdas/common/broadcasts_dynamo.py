"""
XOMIFY Broadcasts DynamoDB Helpers
==================================
Access for the broadcasts feature.

Table: xomify-broadcasts  (PK `broadcastId` [S])
- attrs: broadcastId, title, body, activeUntil(ISO|None), createdAt(ISO),
         createdBy(email), ttl(epoch int|absent)

A broadcast is "active" when `activeUntil` is null OR parses to a time strictly
after now. The table is tiny (admin-authored notices), so active filtering is a
scan-and-filter — matching the `full_table_scan` usage elsewhere.
"""

from datetime import datetime, timezone

import boto3

from lambdas.common.constants import AWS_DEFAULT_REGION, BROADCASTS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.errors import DynamoDBError
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO-8601 string to a tz-aware datetime (assume UTC if naive)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value[:-1] if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_active(broadcast: dict, now: datetime | None = None) -> bool:
    """True when the broadcast has no expiry or its expiry is still in the future."""
    active_until = broadcast.get("activeUntil")
    if not active_until:
        return True
    parsed = _parse_iso(active_until)
    if parsed is None:
        # Unparseable expiry — treat as active rather than silently hiding it.
        return True
    reference = now or datetime.now(timezone.utc)
    return parsed > reference


def put_broadcast(item: dict) -> None:
    try:
        dynamodb.Table(BROADCASTS_TABLE_NAME).put_item(Item=item)
    except Exception as err:
        log.error(f"put_broadcast failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="put_broadcast",
            table=BROADCASTS_TABLE_NAME,
        )


def get_all_broadcasts() -> list[dict]:
    """Return every broadcast row (admin listing)."""
    return full_table_scan(BROADCASTS_TABLE_NAME)


def get_active_broadcasts() -> list[dict]:
    """Return only currently-active broadcasts."""
    now = datetime.now(timezone.utc)
    return [b for b in get_all_broadcasts() if is_active(b, now)]


def delete_broadcast(broadcast_id: str) -> None:
    try:
        dynamodb.Table(BROADCASTS_TABLE_NAME).delete_item(
            Key={"broadcastId": broadcast_id}
        )
    except Exception as err:
        log.error(f"delete_broadcast failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_broadcast",
            table=BROADCASTS_TABLE_NAME,
        )
