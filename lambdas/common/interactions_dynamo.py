"""
XOMIFY Share Interactions DynamoDB Helpers
==========================================
Database operations for Share Interactions table.

Table Structure:
- PK: shareId (string)
- SK: email (string)

Attributes:
- action: "like" | "love" | "fire" | etc
- createdAt: timestamp
"""

from datetime import datetime, timezone
from collections import Counter
import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARE_INTERACTIONS_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


# ============================================
# Upsert Interaction
# ============================================
def upsert_interaction(share_id: str, email: str, action: str):
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)

        item = {
            "shareId": share_id,
            "email": email,
            "action": action,
            "createdAt": _get_timestamp()
        }

        table.put_item(Item=item)
        log.info(f"Interaction upserted: share={share_id}, user={email}, action={action}")
        return True

    except Exception as err:
        log.error(f"Upsert Interaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="upsert_interaction",
            table=SHARE_INTERACTIONS_TABLE_NAME
        )


# ============================================
# Delete Interaction (toggle off)
# ============================================
def delete_interaction(share_id: str, email: str):
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)

        table.delete_item(
            Key={
                "shareId": share_id,
                "email": email
            }
        )
        log.info(f"Interaction deleted: share={share_id}, user={email}")
        return True

    except Exception as err:
        log.error(f"Delete Interaction failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_interaction",
            table=SHARE_INTERACTIONS_TABLE_NAME
        )


# ============================================
# List Interactions For Share
# ============================================
def list_interactions_for_share(share_id: str):
    try:
        table = dynamodb.Table(SHARE_INTERACTIONS_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key("shareId").eq(share_id)
        )

        return response["Items"]

    except Exception as err:
        log.error(f"List Interactions For Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_interactions_for_share",
            table=SHARE_INTERACTIONS_TABLE_NAME
        )


# ============================================
# Count Interactions For Share (by action)
# ============================================
def count_interactions_for_share(share_id: str) -> dict:
    """
    Returns a dict keyed by action with counts.
    Example: {"like": 3, "fire": 1}
    """
    try:
        items = list_interactions_for_share(share_id)
        counts = Counter(item.get("action") for item in items if item.get("action"))
        return dict(counts)

    except Exception as err:
        log.error(f"Count Interactions For Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="count_interactions_for_share",
            table=SHARE_INTERACTIONS_TABLE_NAME
        )
