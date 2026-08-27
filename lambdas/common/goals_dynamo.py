"""
XOMIFY Goals DynamoDB Helpers
=============================
Single-table access for the weekly-goals feature.

Table: xomify-goals  (PK `email` [S], SK `sk` [S])

Row shapes (by sk prefix):
- Goal row:     sk = GOAL#{goalId}
    goalId, metric, target(int), label, icon, createdAt, updatedAt
- History row:  sk = HIST#{weekStart}      (one per ISO week, upserted)
    weekStart(YYYY-MM-DD, Monday), allMet(bool), metCount(int),
    totalCount(int), recordedAt

PROGRESS IS NOT STORED. `current` and `completed` are derived client-side from
recently-played, which is where the listening data already lives. Persisting a
computed number would immediately go stale — the week keeps moving after the
write — and give two clients something to disagree about.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.constants import AWS_DEFAULT_REGION, GOALS_TABLE_NAME
from lambdas.common.errors import DynamoDBError
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)

GOAL_PREFIX = "GOAL#"
HIST_PREFIX = "HIST#"

#: Keeps a runaway client from writing an unbounded goal list.
MAX_GOALS = 20
#: A year of weeks. History is for a streak display, not an archive.
MAX_HISTORY = 52


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table():
    return dynamodb.Table(GOALS_TABLE_NAME)


def get_goals(email: str) -> list[dict[str, Any]]:
    """Every goal row for a user, in insertion order by id."""
    try:
        response = _table().query(
            KeyConditionExpression=Key("email").eq(email)
            & Key("sk").begins_with(GOAL_PREFIX)
        )
        return [_strip_keys(item) for item in response.get("Items", [])]
    except Exception as err:
        log.error(f"get_goals failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err), function="get_goals", table=GOALS_TABLE_NAME
        )


def replace_goals(email: str, goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Replace the user's whole goal set.

    Whole-set replace rather than per-goal CRUD: the client edits a short list
    and saves it, and a partial update protocol would need delete tracking to
    handle removals — three endpoints and a sync bug for no gain at this size.
    """
    table = _table()
    now = _iso_now()
    trimmed = goals[:MAX_GOALS]

    try:
        existing = {
            item["sk"]
            for item in table.query(
                KeyConditionExpression=Key("email").eq(email)
                & Key("sk").begins_with(GOAL_PREFIX),
                ProjectionExpression="sk",
            ).get("Items", [])
        }

        written: set[str] = set()
        with table.batch_writer() as batch:
            for goal in trimmed:
                sk = f"{GOAL_PREFIX}{goal['goalId']}"
                written.add(sk)
                batch.put_item(Item={
                    "email": email,
                    "sk": sk,
                    "goalId": goal["goalId"],
                    "metric": goal["metric"],
                    "target": int(goal["target"]),
                    "label": goal["label"],
                    "icon": goal.get("icon") or "target",
                    "createdAt": goal.get("createdAt") or now,
                    "updatedAt": now,
                })
            # Anything the client no longer sends is a deletion.
            for stale in existing - written:
                batch.delete_item(Key={"email": email, "sk": stale})

        return [
            {**goal, "icon": goal.get("icon") or "target", "target": int(goal["target"])}
            for goal in trimmed
        ]
    except Exception as err:
        log.error(f"replace_goals failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err), function="replace_goals", table=GOALS_TABLE_NAME
        )


def get_history(email: str, limit: int = MAX_HISTORY) -> list[dict[str, Any]]:
    """Week history, most recent first."""
    try:
        response = _table().query(
            KeyConditionExpression=Key("email").eq(email)
            & Key("sk").begins_with(HIST_PREFIX),
            # `weekStart` is ISO, so the sk sorts chronologically; descending
            # gives newest-first without sorting in the handler.
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_strip_keys(item) for item in response.get("Items", [])]
    except Exception as err:
        log.error(f"get_history failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err), function="get_history", table=GOALS_TABLE_NAME
        )


def upsert_week(email: str, entry: dict[str, Any]) -> dict[str, Any]:
    """
    Record (or correct) one week's outcome.

    Upsert rather than append: a week is re-evaluated every time the user opens
    the page while it is still running, and appending would leave one row per
    visit for the same seven days.
    """
    week_start = entry["weekStart"]
    item = {
        "email": email,
        "sk": f"{HIST_PREFIX}{week_start}",
        "weekStart": week_start,
        "allMet": bool(entry.get("allMet")),
        "metCount": int(entry.get("metCount", 0)),
        "totalCount": int(entry.get("totalCount", 0)),
        "recordedAt": _iso_now(),
    }
    try:
        _table().put_item(Item=item)
        return _strip_keys(item)
    except Exception as err:
        log.error(f"upsert_week failed for {email}: {err}")
        raise DynamoDBError(
            message=str(err), function="upsert_week", table=GOALS_TABLE_NAME
        )


def _strip_keys(item: dict[str, Any]) -> dict[str, Any]:
    """Drop the table keys — `email` and `sk` are storage, not payload."""
    return {k: v for k, v in item.items() if k not in ("email", "sk")}
