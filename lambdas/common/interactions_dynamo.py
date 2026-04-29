"""
XOMIFY Share Interactions DynamoDB Helpers
==========================================
Database operations for the xomify-share-interactions table.

Table Structure:
- PK: shareId (string)
- SK: email (string)

Attributes:
- shareId / email (keys)
- sharedBy: string (denormalized author email — lets digest / threshold logic
  answer "who should be notified" without a second read)
- queued: bool (viewer has queued this share's track)
- rated: bool (viewer has rated this share's track)
- rating: number (1.0-5.0, only present when rated=True)
- queuedAt / ratedAt / createdAt / updatedAt: ISO8601 UTC timestamps
- action: str (legacy single-action field, retained for backward-compat with
  the prior shape but no longer primary)
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARE_INTERACTIONS_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

VALID_ACTIONS = {"queued", "rated", "unqueued", "unrated"}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================
# Set Reaction (action in {queued, rated})
# ============================================
def set_reaction(
    share_id: str,
    email: str,
    shared_by: str,
    action: str,
    rating: Optional[float] = None,
) -> dict[str, Any]:
    """
    Idempotent UpdateItem flipping the queued/rated attribute for the given viewer.

    Returns the updated item attributes.
    """
    if action not in {"queued", "rated"}:
        raise ValueError(f"set_reaction requires action in (queued, rated); got {action!r}")

    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        now_iso = _iso_now()
        attr_name = "queued" if action == "queued" else "rated"
        ts_attr = "queuedAt" if action == "queued" else "ratedAt"

        update_parts = [
            f"#{attr_name} = :true_",
            "#sharedBy = :sharedBy",
            "#updatedAt = :now",
            f"#{ts_attr} = :now",
            "#createdAt = if_not_exists(#createdAt, :now)",
            "#action = :action",
        ]
        expr_attr_names: dict[str, str] = {
            f"#{attr_name}": attr_name,
            "#sharedBy": "sharedBy",
            "#updatedAt": "updatedAt",
            f"#{ts_attr}": ts_attr,
            "#createdAt": "createdAt",
            "#action": "action",
        }
        expr_attr_values: dict[str, Any] = {
            ":true_": True,
            ":sharedBy": shared_by,
            ":now": now_iso,
            ":action": action,
        }

        if action == "rated":
            if rating is None:
                raise ValueError("rating required when action=rated")
            update_parts.append("#rating = :rating")
            expr_attr_names["#rating"] = "rating"
            expr_attr_values[":rating"] = rating

        response = table.update_item(
            Key={"shareId": share_id, "email": email},
            UpdateExpression="SET " + ", ".join(update_parts),
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
        log.info(
            f"Reaction set: share={share_id}, user={email}, action={action}"
        )
        return response.get("Attributes", {})

    except ValueError:
        raise
    except Exception as err:
        log.error(f"Set Reaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="set_reaction",
            table=SHARE_INTERACTIONS_TABLE_NAME,
        )


# ============================================
# Clear Reaction (action in {unqueued, unrated})
# ============================================
def clear_reaction(share_id: str, email: str, action: str) -> dict[str, Any]:
    """Flip a reaction attribute off; leaves the row in place so the opposite
    attribute survives (e.g. unqueue keeps rating intact)."""
    if action not in {"unqueued", "unrated"}:
        raise ValueError(
            f"clear_reaction requires action in (unqueued, unrated); got {action!r}"
        )

    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        now_iso = _iso_now()
        target = "queued" if action == "unqueued" else "rated"

        update_parts = [
            f"#{target} = :false_",
            "#updatedAt = :now",
            "#action = :action",
        ]
        expr_attr_names = {
            f"#{target}": target,
            "#updatedAt": "updatedAt",
            "#action": "action",
        }
        expr_attr_values: dict[str, Any] = {
            ":false_": False,
            ":now": now_iso,
            ":action": action,
        }
        remove_parts: list[str] = []
        if target == "rated":
            remove_parts.append("#rating")
            expr_attr_names["#rating"] = "rating"

        update_expr = "SET " + ", ".join(update_parts)
        if remove_parts:
            update_expr += " REMOVE " + ", ".join(remove_parts)

        response = table.update_item(
            Key={"shareId": share_id, "email": email},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_attr_names,
            ExpressionAttributeValues=expr_attr_values,
            ReturnValues="ALL_NEW",
        )
        log.info(
            f"Reaction cleared: share={share_id}, user={email}, action={action}"
        )
        return response.get("Attributes", {})

    except ValueError:
        raise
    except Exception as err:
        log.error(f"Clear Reaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="clear_reaction",
            table=SHARE_INTERACTIONS_TABLE_NAME,
        )


# ============================================
# Get Reaction
# ============================================
def get_reaction(share_id: str, email: str) -> Optional[dict[str, Any]]:
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        response = table.get_item(Key={"shareId": share_id, "email": email})
        return response.get("Item")
    except Exception as err:
        log.error(f"Get Reaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_reaction",
            table=SHARE_INTERACTIONS_TABLE_NAME,
        )


# ============================================
# List Reactions For Share
# ============================================
def list_reactions_for_share(share_id: str) -> list[dict[str, Any]]:
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key("shareId").eq(share_id)
        )
        return response.get("Items", [])
    except Exception as err:
        log.error(f"List Reactions For Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_reactions_for_share",
            table=SHARE_INTERACTIONS_TABLE_NAME,
        )


# Back-compat alias — earlier handler code called this name.
def list_interactions_for_share(share_id: str) -> list[dict[str, Any]]:
    return list_reactions_for_share(share_id)


# ============================================
# Count Distinct Reactors
# ============================================
def count_distinct_reactors(share_id: str) -> int:
    """
    Count rows where the viewer has an active reaction
    (queued=True OR rated=True). One row per viewer, so this is the
    distinct-reactor count by construction.
    """
    items = list_reactions_for_share(share_id)
    return sum(1 for item in items if item.get("queued") or item.get("rated"))


# ============================================
# Back-compat counters (legacy action histogram)
# ============================================
def count_interactions_for_share(share_id: str) -> dict:
    """Legacy count-by-action histogram. Retained for old callers."""
    items = list_reactions_for_share(share_id)
    counts = Counter(item.get("action") for item in items if item.get("action"))
    return dict(counts)


# ============================================
# Enrichment helper (used by shares_feed / shares_user)
# ============================================
def build_enrichment(
    share_id: str,
    viewer_email: str,
    *,
    track_id: Optional[str] = None,
    sharer_email: Optional[str] = None,
) -> dict[str, Any]:
    """
    Inspect all reaction rows for a share and collapse them into the four
    counts/flags the iOS feed card needs.

    `track_id` and `sharer_email` enable a fallback into the canonical
    track-ratings table for viewer/sharer ratings -- the feed-card rate
    button writes to track-ratings via /ratings/publish without writing
    a share-interactions row, so without this fallback the rating is
    invisible on the feed card after refresh.
    """
    items = list_reactions_for_share(share_id)
    queued_count = 0
    rated_count = 0
    viewer_has_queued = False
    viewer_rating: Optional[float] = None
    sharer_rating: Optional[float] = None

    for item in items:
        email = item.get("email")
        shared_by = item.get("sharedBy")
        if item.get("queued"):
            queued_count += 1
        if item.get("rated"):
            rated_count += 1
        if email == viewer_email:
            viewer_has_queued = bool(item.get("queued"))
            rating = item.get("rating")
            if rating is not None:
                try:
                    viewer_rating = float(rating)
                except (TypeError, ValueError):
                    viewer_rating = None
        if shared_by and email == shared_by:
            rating = item.get("rating")
            if rating is not None:
                try:
                    sharer_rating = float(rating)
                except (TypeError, ValueError):
                    sharer_rating = None

    # Fallback: when the canonical track-ratings table has a row but the
    # share-interactions row doesn't carry the rating (writes via
    # /ratings/publish bypass the interactions table), source from there.
    if track_id:
        if viewer_rating is None:
            viewer_rating = _track_rating_value(viewer_email, track_id)
        if sharer_rating is None and sharer_email:
            sharer_rating = _track_rating_value(sharer_email, track_id)
        if rated_count == 0 and (viewer_rating is not None or sharer_rating is not None):
            rated_count = sum(
                1 for v in (viewer_rating, sharer_rating) if v is not None
            )

    return {
        "queuedCount": queued_count,
        "ratedCount": rated_count,
        "viewerHasQueued": viewer_has_queued,
        "viewerRating": viewer_rating,
        "sharerRating": sharer_rating,
    }


def _track_rating_value(email: str, track_id: str) -> Optional[float]:
    """Best-effort lookup into the canonical track-ratings table; never raises."""
    try:
        from lambdas.common.track_ratings_dynamo import (
            get_single_track_rating_for_user,
        )

        row = get_single_track_rating_for_user(email, track_id)
        if not row:
            return None
        rating = row.get("rating")
        if rating is None:
            return None
        return float(rating)
    except Exception as err:
        log.warning(f"track-rating fallback failed (email={email}, trackId={track_id}): {err}")
        return None


# ============================================
# Legacy single-action helpers (kept for callers still on the old shape)
# ============================================
def upsert_interaction(share_id: str, email: str, action: str) -> bool:
    """Legacy helper — writes a single action row without the queued/rated
    attribute split. New callers should use set_reaction / clear_reaction."""
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        item = {
            "shareId": share_id,
            "email": email,
            "action": action,
            "createdAt": _iso_now(),
        }
        table.put_item(Item=item)
        return True
    except Exception as err:
        log.error(f"Legacy upsert_interaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="upsert_interaction",
            table=SHARE_INTERACTIONS_TABLE_NAME,
        )


def delete_interaction(share_id: str, email: str) -> bool:
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        table.delete_item(Key={"shareId": share_id, "email": email})
        return True
    except Exception as err:
        log.error(f"Legacy delete_interaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_interaction",
            table=SHARE_INTERACTIONS_TABLE_NAME,
        )
