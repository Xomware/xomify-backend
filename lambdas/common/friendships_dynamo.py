"""
XOMIFY Friendships DynamoDB Helpers
=====================================
Database operations for Friendships table.

Table Structure:
- PK: email (string)
- SK: friendEmail (string)
- status: "pending" | "accepted" | "blocked"
- direction: "outgoing" | "incoming"
- createdAt: timestamp
- acceptedAt: timestamp
"""

from datetime import datetime, timezone, timedelta
import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import FRIENDSHIPS_TABLE_NAME

log = get_logger(__file__)

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

# ============================================
# List All Friends for User
# ============================================
def list_all_friends_for_user(email: str):
    try:
        log.info(f"Searching friendship table for all friends for {email}..")
        table = dynamodb.Table(FRIENDSHIPS_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key("email").eq(email)
        )

        items = response["Items"]
        return items
    except Exception as err:
        log.error(f"List All Friends for User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_all_friends_for_user",
            table=FRIENDSHIPS_TABLE_NAME
        )
    
# ============================================
# Send Friend Request
# ============================================
def send_friend_request(email: str, request_email: str):
    try:
        client = boto3.client("dynamodb")

        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Item": {
                            "email": {"S": email},
                            "friendEmail": {"S": request_email},
                            "status": {"S": "pending"},
                            "direction": {"S": "outgoing"},
                            "createdAt": {"S": _get_timestamp()}
                        },
                        "ConditionExpression": "attribute_not_exists(email) AND attribute_not_exists(friendEmail)"
                    }
                },
                {
                    "Put": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Item": {
                            "email": {"S": request_email},
                            "friendEmail": {"S": email},
                            "status": {"S": "pending"},
                            "direction": {"S": "incoming"},
                            "createdAt": {"S": _get_timestamp()}
                        },
                        "ConditionExpression": "attribute_not_exists(email) AND attribute_not_exists(friendEmail)"
                    }
                }
            ]
        )
        log.info(f"Friends request sent from {email} to {request_email}")
        return True

    except Exception as err:
        log.error(f"Send Friend Request: {err}")
        raise DynamoDBError(
            message=str(err),
            function="send_friend_request",
            table=FRIENDSHIPS_TABLE_NAME
        )
    
# ============================================
# Accept Friend Request
# ============================================
def accept_friend_request(email: str, request_email: str):
    try:
        client = boto3.client("dynamodb")
        client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Key": {
                            "email": {"S": email},
                            "friendEmail": {"S": request_email}
                        },
                        "UpdateExpression": "SET #status = :accepted, acceptedAt = :ts",
                        "ExpressionAttributeNames": {
                            "#status": "status"
                        },
                        "ExpressionAttributeValues": {
                            ":accepted": {"S": "accepted"},
                            ":ts": {"S": _get_timestamp()}
                        }
                    }
                },
                {
                    "Update": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Key": {
                            "email": {"S": request_email},
                            "friendEmail": {"S": email}
                        },
                        "UpdateExpression": "SET #status = :accepted, acceptedAt = :ts",
                        "ExpressionAttributeNames": {
                            "#status": "status"
                        },
                        "ExpressionAttributeValues": {
                            ":accepted": {"S": "accepted"},
                            ":ts": {"S": _get_timestamp()}
                        }
                    }
                }
            ]
        )
        log.info(f"Friend request accepted between {email} and {request_email}")
        return True

    except Exception as err:
        log.error(f"Accept Friend Request: {err}")
        raise DynamoDBError(
            message=str(err),
            function="accept_friend_request",
            table=FRIENDSHIPS_TABLE_NAME
        )
    
# ============================================
# Reject Friend Request
# ============================================
def delete_friends(email: str, request_email: str):
    try:
        client = boto3.client("dynamodb")
        client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Key": {
                            "email": {"S": email},
                            "friendEmail": {"S": request_email}
                        }
                    }
                },
                {
                    "Delete": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Key": {
                            "email": {"S": request_email},
                            "friendEmail": {"S": email}
                        }
                    }
                }
            ]
        )
        log.info(f"Friends deleted between {email} and {request_email}")
        return True

    except Exception as err:
        log.error(f"Delete Friends error: {err}")
        raise DynamoDBError(
            message=str(err),
            function="reject_friend_request",
            table=FRIENDSHIPS_TABLE_NAME
        )


# ============================================
# Are Two Users Accepted Friends?
# ============================================
def are_users_friends(email: str, other_email: str) -> bool:
    """Return True iff ``email`` and ``other_email`` have an accepted friendship.

    Uses a direct GetItem on the base table (PK=email, SK=friendEmail) so
    this stays cheap — no scan, no extra GSI round-trip. We intentionally
    only check the caller's row: rows are written symmetrically by
    ``accept_friend_request`` / ``create_accepted_friendship`` so a single
    read is sufficient. If the caller's row is missing or not in the
    ``accepted`` state, the relationship doesn't count for visibility
    gates.

    Returns False on the same-email case (callers should special-case
    self-access before calling this).
    """
    if not email or not other_email or email == other_email:
        return False
    try:
        table = dynamodb.Table(FRIENDSHIPS_TABLE_NAME)
        res = table.get_item(Key={"email": email, "friendEmail": other_email})
        item = res.get("Item")
        if not item:
            return False
        return item.get("status") == "accepted"
    except Exception as err:
        log.error(f"are_users_friends failed for {email}/{other_email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="are_users_friends",
            table=FRIENDSHIPS_TABLE_NAME,
        )


# ============================================
# Create Accepted Friendship (from invite flow)
# ============================================
def create_accepted_friendship(sender_email: str, recipient_email: str):
    """
    Write both directional friendship rows in a single transaction with
    status='accepted' and matching createdAt + acceptedAt timestamps.

    Guarded by attribute_not_exists on both puts so a retry after a partial
    prior write does not overwrite existing rows (caller should fall back to
    the existing pending/accept flow if the transaction fails with
    ConditionalCheckFailedException).
    """
    try:
        client = boto3.client("dynamodb")
        ts = _get_timestamp()

        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Item": {
                            "email": {"S": sender_email},
                            "friendEmail": {"S": recipient_email},
                            "status": {"S": "accepted"},
                            "direction": {"S": "outgoing"},
                            "createdAt": {"S": ts},
                            "acceptedAt": {"S": ts},
                        },
                        "ConditionExpression": "attribute_not_exists(email) AND attribute_not_exists(friendEmail)",
                    }
                },
                {
                    "Put": {
                        "TableName": FRIENDSHIPS_TABLE_NAME,
                        "Item": {
                            "email": {"S": recipient_email},
                            "friendEmail": {"S": sender_email},
                            "status": {"S": "accepted"},
                            "direction": {"S": "incoming"},
                            "createdAt": {"S": ts},
                            "acceptedAt": {"S": ts},
                        },
                        "ConditionExpression": "attribute_not_exists(email) AND attribute_not_exists(friendEmail)",
                    }
                },
            ]
        )
        log.info(
            f"Accepted friendship created between {sender_email} and {recipient_email}"
        )
        return True

    except Exception as err:
        log.error(f"Create Accepted Friendship error: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_accepted_friendship",
            table=FRIENDSHIPS_TABLE_NAME,
        )