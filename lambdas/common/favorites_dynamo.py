"""
XOMIFY Favorites DynamoDB Helpers
=================================
Single-table access for the favorites feature.

Table: xomify-favorites  (PK `email` [S], SK `sk` [S])

Row shapes (by sk prefix):
- List row:      sk = LIST#{year}#{listId}
    listId, year(int), category, genreLabel(str|None),
    items:[{rank, spotifyId, name, artist, imageUrl}], createdAt, updatedAt
- History row:   sk = HIST#{listId}#{ts}#{seq}   (append-only)
    listId, spotifyId, fromRank(int|None), toRank(int|None), ts(ISO)
- Reminder marker: sk = REMINDER#{year}   (cron idempotency)  -> sentAt
"""

from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.constants import AWS_DEFAULT_REGION, FAVORITES_TABLE_NAME
from lambdas.common.errors import DynamoDBError
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_sk(year: int, list_id: str) -> str:
    return f"LIST#{year}#{list_id}"


def _table():
    return dynamodb.Table(FAVORITES_TABLE_NAME)


# ============================================
# List rows
# ============================================

def get_lists_for_year(email: str, year: int) -> list[dict]:
    """Return every list row (overall + custom) for a user's year."""
    try:
        response = _table().query(
            KeyConditionExpression=Key("email").eq(email)
            & Key("sk").begins_with(f"LIST#{year}#"),
        )
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = _table().query(
                KeyConditionExpression=Key("email").eq(email)
                & Key("sk").begins_with(f"LIST#{year}#"),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return items
    except Exception as err:
        log.error(f"get_lists_for_year failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_lists_for_year",
            table=FAVORITES_TABLE_NAME,
        )


def get_list(email: str, year: int, list_id: str) -> dict | None:
    """Return a single list row, or None if it does not exist."""
    try:
        response = _table().get_item(Key={"email": email, "sk": list_sk(year, list_id)})
        return response.get("Item")
    except Exception as err:
        log.error(f"get_list failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_list",
            table=FAVORITES_TABLE_NAME,
        )


def put_list(
    email: str,
    year: int,
    list_id: str,
    category: str,
    genre_label: str | None,
    items: list[dict],
    created_at: str | None = None,
) -> dict:
    """Create or overwrite a list row. Preserves createdAt when provided."""
    now = _iso_now()
    item = {
        "email": email,
        "sk": list_sk(year, list_id),
        "listId": list_id,
        "year": year,
        "category": category,
        "genreLabel": genre_label,
        "items": items,
        "createdAt": created_at or now,
        "updatedAt": now,
    }
    try:
        _table().put_item(Item=item)
        return item
    except Exception as err:
        log.error(f"put_list failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="put_list",
            table=FAVORITES_TABLE_NAME,
        )


def delete_list(email: str, year: int, list_id: str) -> None:
    try:
        _table().delete_item(Key={"email": email, "sk": list_sk(year, list_id)})
    except Exception as err:
        log.error(f"delete_list failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_list",
            table=FAVORITES_TABLE_NAME,
        )


# ============================================
# History rows (append-only)
# ============================================

def append_history_events(email: str, list_id: str, events: list[dict]) -> None:
    """
    Append rank-change events for a list. Each event dict must carry
    `spotifyId`, `fromRank`, `toRank`. `ts` and a zero-padded `seq` produce a
    unique, chronologically-sortable sort key.
    """
    if not events:
        return
    ts = _iso_now()
    try:
        table = _table()
        with table.batch_writer() as batch:
            for seq, event in enumerate(events):
                batch.put_item(
                    Item={
                        "email": email,
                        "sk": f"HIST#{list_id}#{ts}#{seq:06d}",
                        "listId": list_id,
                        "spotifyId": event["spotifyId"],
                        "fromRank": event.get("fromRank"),
                        "toRank": event.get("toRank"),
                        "ts": ts,
                    }
                )
    except Exception as err:
        log.error(f"append_history_events failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="append_history_events",
            table=FAVORITES_TABLE_NAME,
        )


def get_history(email: str, list_id: str) -> list[dict]:
    """Return all history rows for a list, chronologically ascending."""
    try:
        response = _table().query(
            KeyConditionExpression=Key("email").eq(email)
            & Key("sk").begins_with(f"HIST#{list_id}#"),
            ScanIndexForward=True,
        )
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = _table().query(
                KeyConditionExpression=Key("email").eq(email)
                & Key("sk").begins_with(f"HIST#{list_id}#"),
                ScanIndexForward=True,
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))
        return items
    except Exception as err:
        log.error(f"get_history failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_history",
            table=FAVORITES_TABLE_NAME,
        )


# ============================================
# Reminder markers (cron idempotency)
# ============================================

def get_reminder_marker(email: str, year: int) -> dict | None:
    try:
        response = _table().get_item(Key={"email": email, "sk": f"REMINDER#{year}"})
        return response.get("Item")
    except Exception as err:
        log.error(f"get_reminder_marker failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_reminder_marker",
            table=FAVORITES_TABLE_NAME,
        )


def put_reminder_marker(email: str, year: int) -> None:
    try:
        _table().put_item(
            Item={
                "email": email,
                "sk": f"REMINDER#{year}",
                "sentAt": _iso_now(),
            }
        )
    except Exception as err:
        log.error(f"put_reminder_marker failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="put_reminder_marker",
            table=FAVORITES_TABLE_NAME,
        )
