"""
XOMIFY Share Listeners DynamoDB Helpers
=======================================
Database operations for the xomify-share-listeners table.

Why a separate table (not folded into share-interactions)?
---------------------------------------------------------
Listened-marking volume will be substantially higher than queued/rated
events — every Queue / Play Now click on a share card writes a row, plus
auto-marks for share authors. Keeping it single-purpose:
  * isolates the higher-write traffic from the queued/rated table
  * gives us a clean place to TTL or cap historical data later
  * keeps the schema readable (one table = one concept)

Table Structure:
- PK: shareId (string)
- SK: email (string)

Attributes:
- shareId / email (keys)
- listenedAt: ISO8601 UTC timestamp — set on FIRST listen via if_not_exists
  so we preserve the original timestamp across re-marks (idempotent).
- source: "queue" | "play" | "author_create" — also pinned via if_not_exists
  so the FIRST marker source survives.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARE_LISTENERS_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

VALID_SOURCES = {"queue", "play", "author_create"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================
# Mark Listened (idempotent upsert)
# ============================================
def mark_listened(
    share_id: str,
    email: str,
    source: str = "queue",
) -> dict[str, Any]:
    """
    Idempotent UpdateItem that records `email` as a listener of `share_id`.

    Uses if_not_exists for both `listenedAt` and `source`, so the FIRST
    listen wins and re-calls are safe no-ops on those fields. `updatedAt`
    moves on every call to make recent-activity queries possible later
    without losing the original listen timestamp.
    """
    if source not in VALID_SOURCES:
        raise ValueError(
            f"mark_listened source must be one of {sorted(VALID_SOURCES)}; got {source!r}"
        )

    try:
        table = dynamodb.Table(SHARE_LISTENERS_TABLE_NAME)
        now_iso = _iso_now()

        response = table.update_item(
            Key={"shareId": share_id, "email": email},
            UpdateExpression=(
                "SET #listenedAt = if_not_exists(#listenedAt, :now), "
                "#source = if_not_exists(#source, :source), "
                "#updatedAt = :now"
            ),
            ExpressionAttributeNames={
                "#listenedAt": "listenedAt",
                "#source": "source",
                "#updatedAt": "updatedAt",
            },
            ExpressionAttributeValues={
                ":now": now_iso,
                ":source": source,
            },
            ReturnValues="ALL_NEW",
        )
        log.info(
            f"Listener marked: share={share_id}, user={email}, source={source}"
        )
        return response.get("Attributes", {})

    except ValueError:
        raise
    except Exception as err:
        log.error(f"mark_listened failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="mark_listened",
            table=SHARE_LISTENERS_TABLE_NAME,
        )


# ============================================
# Bulk Mark Listened
# ============================================
def mark_listened_bulk(
    share_ids: list[str],
    email: str,
    source: str = "queue",
) -> int:
    """
    Mark up to 25 shares as listened for the given viewer.

    Implementation note: BatchWriteItem only supports PutItem/DeleteItem and
    has no conditional-write support, so we cannot use it here without
    losing the if_not_exists idempotency on `listenedAt`. We loop UpdateItem
    instead — at most 25 round-trips, which is acceptable for this endpoint.

    Returns the number of rows successfully written. Errors on individual
    rows are logged and skipped so a single bad shareId doesn't abort the
    whole call.
    """
    if not share_ids:
        return 0
    if len(share_ids) > 25:
        raise ValueError(
            f"mark_listened_bulk capped at 25 share_ids per call; got {len(share_ids)}"
        )
    if source not in VALID_SOURCES:
        raise ValueError(
            f"mark_listened_bulk source must be one of {sorted(VALID_SOURCES)}; got {source!r}"
        )

    written = 0
    for share_id in share_ids:
        try:
            mark_listened(share_id, email, source=source)
            written += 1
        except DynamoDBError as err:
            log.warning(
                f"mark_listened_bulk: skipping share={share_id} email={email}: {err}"
            )
            continue
    return written


# ============================================
# List Listeners For Share
# ============================================
def list_listeners_for_share(share_id: str) -> list[dict[str, Any]]:
    try:
        table = dynamodb.Table(SHARE_LISTENERS_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key("shareId").eq(share_id)
        )
        return response.get("Items", [])
    except Exception as err:
        log.error(f"list_listeners_for_share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_listeners_for_share",
            table=SHARE_LISTENERS_TABLE_NAME,
        )


# ============================================
# Count Listeners
# ============================================
def count_listeners(share_id: str) -> int:
    """Return the number of distinct listeners for a share."""
    return len(list_listeners_for_share(share_id))


# ============================================
# Has Listened
# ============================================
def has_listened(share_id: str, email: str) -> bool:
    """Return True if (share_id, email) has a listener row, False otherwise."""
    try:
        table = dynamodb.Table(SHARE_LISTENERS_TABLE_NAME)
        response = table.get_item(Key={"shareId": share_id, "email": email})
        return "Item" in response and response["Item"] is not None
    except Exception as err:
        log.error(f"has_listened failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="has_listened",
            table=SHARE_LISTENERS_TABLE_NAME,
        )
