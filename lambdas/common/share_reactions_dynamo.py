"""
XOMIFY Share Reactions DynamoDB Helpers
=======================================
Database operations for the xomify-share-reactions table.

Stores per-user emoji reactions on a share. One row per
(shareId, email, reaction) — multiple emoji per user per share is allowed.

Table Structure:
- PK: shareId (string)
- SK: emailReaction (string)  -- "<email>#<reaction>"

Attributes:
- shareId: string (parent share id)
- emailReaction: string (sort key, encodes email + reaction)
- email: string (reactor email, denormalized for filter convenience)
- reaction: string (one of the allowed emoji slugs — see VALID_REACTIONS)
- createdAt: ISO8601 UTC timestamp
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARE_REACTIONS_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


# Allowed emoji slugs. Mirrored on the iOS client; reject everything else
# server-side so a future client typo can't pollute the table.
VALID_REACTIONS: set[str] = {
    "fire",
    "heart",
    "laugh",
    "mind_blown",
    "sad",
    "thumbs_up",
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sort_key(email: str, reaction: str) -> str:
    return f"{email}#{reaction}"


# ============================================
# Get Reaction Row
# ============================================
def get_reaction(share_id: str, email: str, reaction: str) -> Optional[dict[str, Any]]:
    """Fetch a single (share, user, emoji) row. Returns None on miss."""
    try:
        table = dynamodb.Table(SHARE_REACTIONS_TABLE_NAME)
        response = table.get_item(
            Key={"shareId": share_id, "emailReaction": _sort_key(email, reaction)}
        )
        return response.get("Item")
    except Exception as err:
        log.error(f"Get Reaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_reaction",
            table=SHARE_REACTIONS_TABLE_NAME,
        )


# ============================================
# Add Reaction
# ============================================
def add_reaction(share_id: str, email: str, reaction: str) -> dict[str, Any]:
    """Insert a (share, user, emoji) row. Returns the persisted item."""
    try:
        table = dynamodb.Table(SHARE_REACTIONS_TABLE_NAME)
        item: dict[str, Any] = {
            "shareId": share_id,
            "emailReaction": _sort_key(email, reaction),
            "email": email,
            "reaction": reaction,
            "createdAt": _iso_now(),
        }
        table.put_item(Item=item)
        log.info(
            f"Reaction added: share={share_id} email={email} reaction={reaction}"
        )
        return item
    except Exception as err:
        log.error(f"Add Reaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="add_reaction",
            table=SHARE_REACTIONS_TABLE_NAME,
        )


# ============================================
# Remove Reaction
# ============================================
def remove_reaction(share_id: str, email: str, reaction: str) -> bool:
    """Hard-delete a (share, user, emoji) row."""
    try:
        table = dynamodb.Table(SHARE_REACTIONS_TABLE_NAME)
        table.delete_item(
            Key={"shareId": share_id, "emailReaction": _sort_key(email, reaction)}
        )
        log.info(
            f"Reaction removed: share={share_id} email={email} reaction={reaction}"
        )
        return True
    except Exception as err:
        log.error(f"Remove Reaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="remove_reaction",
            table=SHARE_REACTIONS_TABLE_NAME,
        )


# ============================================
# List Reactions For Share
# ============================================
def list_reactions(share_id: str) -> list[dict[str, Any]]:
    """Return every reaction row for a share (paginates internally)."""
    try:
        table = dynamodb.Table(SHARE_REACTIONS_TABLE_NAME)
        items: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("shareId").eq(share_id),
        }
        while True:
            response = table.query(**kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items
    except Exception as err:
        log.error(f"List Reactions failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_reactions",
            table=SHARE_REACTIONS_TABLE_NAME,
        )


# ============================================
# Build Summary (counts + viewer's own reactions)
# ============================================
def build_reaction_summary(
    share_id: str,
    viewer_email: str,
) -> dict[str, Any]:
    """
    Collapse all reaction rows for a share into:
        - counts: {reaction: int} (only emoji slugs with > 0 are present)
        - viewerReactions: list[str] (emoji slugs the viewer has tapped)

    One Query per share — fine at v1 feed sizes.
    """
    rows = list_reactions(share_id)
    counts: Counter = Counter()
    viewer: list[str] = []
    for row in rows:
        reaction = row.get("reaction")
        if not reaction or reaction not in VALID_REACTIONS:
            # Defensive — skip rows that pre-date validation or use legacy slugs.
            continue
        counts[reaction] += 1
        if row.get("email") == viewer_email:
            viewer.append(reaction)
    return {
        "counts": dict(counts),
        "viewerReactions": viewer,
    }
