"""
XOMIFY Shares DynamoDB Helpers
==============================
Database operations for Shares table.

Table Structure:
- PK: shareId (string)
- GSI: email-createdAt-index (PK: email, SK: createdAt)

Attributes:
- shareId: string (uuid4)
- email: string (author)
- type: "wrapped" | "release_radar" | "track" | "playlist"
- payload: dict (type-specific data)
- caption: string (optional)
- createdAt: timestamp
"""

from datetime import datetime, timezone
from uuid import uuid4
import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import SHARES_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


# ============================================
# Create Share
# ============================================
def create_share(email: str, share_type: str, payload: dict, caption: str | None = None) -> str:
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)

        share_id = str(uuid4())
        timestamp = _get_timestamp()

        item = {
            "shareId": share_id,
            "email": email,
            "type": share_type,
            "payload": payload,
            "createdAt": timestamp
        }

        if caption:
            item["caption"] = caption

        table.put_item(Item=item)
        log.info(f"Share {share_id} created by {email} (type={share_type})")
        return share_id

    except Exception as err:
        log.error(f"Create Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_share",
            table=SHARES_TABLE_NAME
        )


# ============================================
# List Shares For User (via GSI)
# ============================================
def list_shares_for_user(email: str, limit: int = 20):
    """
    Queries the email-createdAt-index GSI to get a user's shares
    ordered by createdAt desc (newest first).
    """
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)
        response = table.query(
            IndexName="email-createdAt-index",
            KeyConditionExpression=Key("email").eq(email),
            ScanIndexForward=False,  # newest first
            Limit=limit
        )

        return response["Items"]

    except Exception as err:
        log.error(f"List Shares For User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_shares_for_user",
            table=SHARES_TABLE_NAME
        )


# ============================================
# Get Share
# ============================================
def get_share(share_id: str):
    try:
        table = dynamodb.Table(SHARES_TABLE_NAME)
        response = table.get_item(Key={"shareId": share_id})
        return response.get("Item")

    except Exception as err:
        log.error(f"Get Share failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_share",
            table=SHARES_TABLE_NAME
        )
