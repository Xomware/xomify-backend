"""
XOMIFY Invites DynamoDB Helpers
===============================
Database operations for Invites table.

Table Structure:
- PK: inviteCode (string, uuid4)

Attributes:
- email: string (issuer)
- createdAt: timestamp
- expiresAt: timestamp
- status: "pending" | "accepted" | "expired"
- usedBy: string (optional, set on accept)
"""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import boto3

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import INVITES_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

INVITE_TTL_DAYS = 7


def _get_timestamp() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _get_expiry_timestamp(days: int = INVITE_TTL_DAYS) -> str:
    """Get UTC timestamp N days from now."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')


# ============================================
# Create Invite
# ============================================
def create_invite(email: str) -> dict:
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)

        invite_code = str(uuid4())
        created_at = _get_timestamp()
        expires_at = _get_expiry_timestamp()

        item = {
            "inviteCode": invite_code,
            "email": email,
            "createdAt": created_at,
            "expiresAt": expires_at,
            "status": "pending"
        }

        table.put_item(Item=item)
        log.info(f"Invite {invite_code} created by {email}")
        return item

    except Exception as err:
        log.error(f"Create Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_invite",
            table=INVITES_TABLE_NAME
        )


# ============================================
# Get Invite
# ============================================
def get_invite(invite_code: str):
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)
        response = table.get_item(Key={"inviteCode": invite_code})
        return response.get("Item")

    except Exception as err:
        log.error(f"Get Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_invite",
            table=INVITES_TABLE_NAME
        )


# ============================================
# Mark Invite Accepted
# ============================================
def mark_invite_accepted(invite_code: str, used_by: str):
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)

        table.update_item(
            Key={"inviteCode": invite_code},
            UpdateExpression="SET #status = :accepted, usedBy = :usedBy, acceptedAt = :ts",
            ExpressionAttributeNames={
                "#status": "status"
            },
            ExpressionAttributeValues={
                ":accepted": "accepted",
                ":usedBy": used_by,
                ":ts": _get_timestamp()
            }
        )
        log.info(f"Invite {invite_code} accepted by {used_by}")
        return True

    except Exception as err:
        log.error(f"Mark Invite Accepted failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="mark_invite_accepted",
            table=INVITES_TABLE_NAME
        )


# ============================================
# Is Invite Expired
# ============================================
def is_invite_expired(invite: dict) -> bool:
    expires_at = invite.get("expiresAt")
    if not expires_at:
        return False
    try:
        expires_dt = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires_dt
    except Exception as err:
        log.warning(f"Could not parse expiresAt {expires_at}: {err}")
        return False
