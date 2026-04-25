"""
XOMIFY Share Comments DynamoDB Helpers
======================================
Database operations for the xomify-share-comments table.

Table Structure:
- PK: shareId (string)
- SK: createdAtId (string)  -- "<ISO8601 createdAt>#<commentId>" so a single
                              Query on the partition returns rows in time
                              order without a separate GSI

Attributes:
- shareId: string (parent share id)
- createdAtId: string (sort key, encodes createdAt + commentId for uniqueness)
- commentId: string (uuid4)
- email: string (author email)
- body: string (raw comment text, length-validated by handler)
- createdAt: ISO8601 UTC timestamp
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARE_COMMENTS_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sort_key(created_at: str, comment_id: str) -> str:
    """Compose the sort key. createdAt first so range queries are time-ordered."""
    return f"{created_at}#{comment_id}"


# ============================================
# Create Comment
# ============================================
def create_comment(share_id: str, email: str, body: str) -> dict[str, Any]:
    """Persist a new comment row and return it."""
    try:
        table = dynamodb.Table(SHARE_COMMENTS_TABLE_NAME)

        comment_id = str(uuid4())
        created_at = _iso_now()
        item: dict[str, Any] = {
            "shareId": share_id,
            "createdAtId": _sort_key(created_at, comment_id),
            "commentId": comment_id,
            "email": email,
            "body": body,
            "createdAt": created_at,
        }
        table.put_item(Item=item)
        log.info(
            f"Comment {comment_id} created on share={share_id} by {email}"
        )
        return item
    except Exception as err:
        log.error(f"Create Comment failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_comment",
            table=SHARE_COMMENTS_TABLE_NAME,
        )


# ============================================
# List Comments
# ============================================
def list_comments(
    share_id: str,
    limit: int = 20,
    before: Optional[str] = None,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """
    Query comments for a share, newest first.

    Args:
        share_id: parent share
        limit: page size (caller should cap)
        before: ISO8601 createdAt cursor — only items strictly older than
                this are returned

    Returns:
        (items, next_before) — next_before is the createdAt of the last item
        on the page when more results may remain, else None.
    """
    try:
        table = dynamodb.Table(SHARE_COMMENTS_TABLE_NAME)

        query_kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("shareId").eq(share_id),
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }

        if before:
            # Sort key is "<createdAt>#<commentId>" — anything strictly less
            # than "<before>#" sorts older than the cursor regardless of
            # which commentId tied at that exact timestamp.
            query_kwargs["KeyConditionExpression"] = (
                Key("shareId").eq(share_id)
                & Key("createdAtId").lt(f"{before}#")
            )

        response = table.query(**query_kwargs)
        items = response.get("Items", [])

        next_before: Optional[str] = None
        if len(items) == limit and items:
            last = items[-1]
            next_before = last.get("createdAt")

        return items, next_before

    except Exception as err:
        log.error(f"List Comments failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_comments",
            table=SHARE_COMMENTS_TABLE_NAME,
        )


# ============================================
# Get Comment
# ============================================
def get_comment(share_id: str, comment_id: str) -> Optional[dict[str, Any]]:
    """Fetch a single comment by (shareId, commentId).

    The sort key is "<createdAt>#<commentId>", so we Query on the partition
    and filter — comments are typically far fewer than reactions per share.
    """
    try:
        table = dynamodb.Table(SHARE_COMMENTS_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key("shareId").eq(share_id),
        )
        for item in response.get("Items", []):
            if item.get("commentId") == comment_id:
                return item
        return None
    except Exception as err:
        log.error(f"Get Comment failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_comment",
            table=SHARE_COMMENTS_TABLE_NAME,
        )


# ============================================
# Delete Comment
# ============================================
def delete_comment(share_id: str, created_at_id: str) -> bool:
    """Hard-delete a comment row by (shareId, createdAtId)."""
    try:
        table = dynamodb.Table(SHARE_COMMENTS_TABLE_NAME)
        table.delete_item(
            Key={"shareId": share_id, "createdAtId": created_at_id}
        )
        log.info(
            f"Comment deleted: share={share_id} createdAtId={created_at_id}"
        )
        return True
    except Exception as err:
        log.error(f"Delete Comment failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_comment",
            table=SHARE_COMMENTS_TABLE_NAME,
        )


# ============================================
# Count Comments
# ============================================
def count_comments(share_id: str) -> int:
    """Return total comment count for a share.

    Uses a Select=COUNT Query to avoid hauling rows back when callers only
    need the number for a feed card or detail page.
    """
    try:
        table = dynamodb.Table(SHARE_COMMENTS_TABLE_NAME)
        total = 0
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("shareId").eq(share_id),
            "Select": "COUNT",
        }
        while True:
            response = table.query(**kwargs)
            total += int(response.get("Count", 0))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return total
    except Exception as err:
        log.error(f"Count Comments failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="count_comments",
            table=SHARE_COMMENTS_TABLE_NAME,
        )
