"""
XOMIFY Shares DynamoDB Helpers
==============================
Database operations for the xomify-shares table.

Table Structure:
- PK: shareId (string)
- GSI: email-createdAt-index (PK=email, SK=createdAt) PROJECTION_ALL

Attributes:
- shareId: string (uuid4)
- email: string (author)
- trackId / trackUri / trackName / artistName / albumName / albumArtUrl: denormalized Spotify metadata
- caption: string, optional, max 140 chars
- moodTag: string, optional, one of hype|chill|sad|party|focus|discovery
- genreTags: list[str], optional, max 3
- createdAt: ISO8601 UTC timestamp
- sharedAt: mirror of createdAt (kept for downstream compatibility)
"""

from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARES_TABLE_NAME, SHARES_EMAIL_INDEX

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _iso_now() -> str:
    """Get current UTC timestamp in ISO8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ============================================
# Create Share
# ============================================
def create_share(
    email: str,
    track_id: str,
    track_uri: str,
    track_name: str,
    artist_name: str,
    album_name: str,
    album_art_url: str,
    caption: Optional[str] = None,
    mood_tag: Optional[str] = None,
    genre_tags: Optional[list[str]] = None,
) -> dict[str, str]:
    """Create a share row; returns {shareId, createdAt}."""
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)

        share_id = str(uuid4())
        created_at = _iso_now()

        item: dict[str, Any] = {
            "shareId": share_id,
            "email": email,
            "trackId": track_id,
            "trackUri": track_uri,
            "trackName": track_name,
            "artistName": artist_name,
            "albumName": album_name,
            "albumArtUrl": album_art_url,
            "createdAt": created_at,
            "sharedAt": created_at,
        }

        if caption is not None:
            item["caption"] = caption
        if mood_tag is not None:
            item["moodTag"] = mood_tag
        if genre_tags is not None:
            item["genreTags"] = genre_tags

        table.put_item(Item=item)
        log.info(f"Share {share_id} created by {email} (track={track_id})")
        return {"shareId": share_id, "createdAt": created_at}

    except Exception as err:
        log.error(f"Create Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_share",
            table=SHARES_TABLE_NAME,
        )


# ============================================
# Get Share
# ============================================
def get_share(share_id: str) -> Optional[dict[str, Any]]:
    """Fetch a share by primary key. Returns None on miss."""
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)
        response = table.get_item(Key={"shareId": share_id})
        return response.get("Item")
    except Exception as err:
        log.error(f"Get Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_share",
            table=SHARES_TABLE_NAME,
        )


# ============================================
# Delete Share
# ============================================
def delete_share(share_id: str) -> bool:
    """Delete a share by primary key."""
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)
        table.delete_item(Key={"shareId": share_id})
        log.info(f"Share {share_id} deleted")
        return True
    except Exception as err:
        log.error(f"Delete Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_share",
            table=SHARES_TABLE_NAME,
        )


# ============================================
# List Shares For User (via GSI)
# ============================================
def list_shares_for_user(
    email: str,
    limit: int = 50,
    before: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    Query email-createdAt-index GSI for a single author's shares, newest first.

    Args:
        email: author email to query
        limit: page size (caller should cap)
        before: ISO8601 createdAt cursor — only items strictly older than this are returned
                (implemented via ExclusiveStartKey)

    Returns:
        (items, next_before) — next_before is the createdAt of the last item if a page
        boundary was reached, else None.
    """
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)

        query_kwargs: dict[str, Any] = {
            "IndexName": SHARES_EMAIL_INDEX,
            "KeyConditionExpression": Key("email").eq(email),
            "ScanIndexForward": False,
            "Limit": limit,
        }

        if before:
            # ExclusiveStartKey needs all GSI + base-table keys
            query_kwargs["ExclusiveStartKey"] = {
                "email": email,
                "createdAt": before,
            }

        response = table.query(**query_kwargs)
        items = response.get("Items", [])

        last_key = response.get("LastEvaluatedKey")
        next_before = last_key["createdAt"] if last_key and "createdAt" in last_key else None

        return items, next_before

    except Exception as err:
        log.error(f"List Shares For User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_shares_for_user",
            table=SHARES_TABLE_NAME,
        )


# ============================================
# Fan-out Feed Query
# ============================================
def query_feed_for_emails(
    emails: list[str],
    limit: int = 50,
    before: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Fan-out across authors in parallel, merge-sort by createdAt desc, return top `limit`.

    `before` applies to every per-email query (filters older than cursor).
    """
    if not emails:
        return []

    all_items: list[dict[str, Any]] = []

    def _fetch(author_email: str) -> list[dict[str, Any]]:
        try:
            items, _ = list_shares_for_user(author_email, limit=limit, before=before)
            return items
        except Exception as err:
            log.warning(f"Feed fan-out failed for {author_email}: {err}")
            return []

    # ThreadPoolExecutor caps at 10 per plan
    max_workers = min(10, max(1, len(emails)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for result in ex.map(_fetch, emails):
            all_items.extend(result)

    all_items.sort(key=lambda s: s.get("createdAt", ""), reverse=True)
    return all_items[:limit]


# ============================================
# Threshold Notification Latch (idempotent)
# ============================================
def mark_threshold_notified(share_id: str, threshold: int) -> bool:
    """
    Atomically mark a share as having fired its queue-threshold notification.

    Uses a DynamoDB conditional UpdateItem on the share row
    (attribute_not_exists(notifiedAtThreshold<N>)) so only one caller wins
    under concurrent writes. Returns True if this call acquired the latch
    and the push should be sent, False if the latch was already taken.
    """
    attr = f"notifiedAtThreshold{threshold}"
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)
        table.update_item(
            Key={"shareId": share_id},
            UpdateExpression=f"SET #a = :now",
            ExpressionAttributeNames={"#a": attr},
            ExpressionAttributeValues={":now": _iso_now()},
            ConditionExpression=f"attribute_not_exists(#a)",
        )
        log.info(f"Threshold latch acquired for share={share_id} threshold={threshold}")
        return True
    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            log.info(
                f"Threshold latch already set for share={share_id} threshold={threshold}"
            )
            return False
        log.error(f"mark_threshold_notified failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="mark_threshold_notified",
            table=SHARES_TABLE_NAME,
        )
    except Exception as err:
        log.error(f"mark_threshold_notified failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="mark_threshold_notified",
            table=SHARES_TABLE_NAME,
        )
