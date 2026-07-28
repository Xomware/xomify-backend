"""
XOMIFY Page-Visit Log DynamoDB Helpers
======================================
Backs the admin Users "where they've been" view. The frontend posts a
lightweight visit event on each route change (POST /visits/log).

Table: xomify-visits
- PK  `email` [S]  — the visiting user
- SK  `ts`    [S]  — "<iso8601 ts>#<rand8>" (unique + time-sortable)
- attrs: path, ttl(epoch int, ~30d)

Keyed by email so a per-user history read is a single Query.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.constants import (
    AWS_DEFAULT_REGION,
    VISITS_TABLE_NAME,
    VISITS_TTL_DAYS,
)
from lambdas.common.errors import DynamoDBError
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def put_visit(email: str, path: str) -> dict:
    """Append a visit row for a user. Raises DynamoDBError on failure."""
    now = datetime.now(timezone.utc)
    ts = now.isoformat()
    item = {
        "email": email,
        "ts": f"{ts}#{uuid.uuid4().hex[:8]}",
        "path": path,
        "visitedAt": ts,
        "ttl": int((now + timedelta(days=VISITS_TTL_DAYS)).timestamp()),
    }
    try:
        dynamodb.Table(VISITS_TABLE_NAME).put_item(Item=item)
        return item
    except Exception as err:
        log.error(f"put_visit failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="put_visit",
            table=VISITS_TABLE_NAME,
        )


def list_visits_for_user(email: str, limit: int = 200) -> list[dict]:
    """Most-recent-first visits for a user."""
    if not VISITS_TABLE_NAME:
        return []
    try:
        resp = dynamodb.Table(VISITS_TABLE_NAME).query(
            KeyConditionExpression=Key("email").eq(email),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get("Items", [])
    except Exception as err:
        log.error(f"list_visits_for_user failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_visits_for_user",
            table=VISITS_TABLE_NAME,
        )
