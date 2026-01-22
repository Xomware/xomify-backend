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
                        "ConditionExpression": "attribute_not_exists(user_email) AND attribute_not_exists(friend_email)"
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
                        "ConditionExpression": "attribute_not_exists(user_email) AND attribute_not_exists(friend_email)"
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
                        "UpdateExpression": "SET status = :accepted, acceptedAt = :ts",
                        "ExpressionAttributeValues": {
                            ":accepted": {"S": "accepted"},
                            ":ts": {"S": _get_timestamp}
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
                        "UpdateExpression": "SET status = :accepted, acceptedAt = :ts",
                        "ExpressionAttributeValues": {
                            ":accepted": {"S": "accepted"},
                            ":ts": {"S": _get_timestamp}
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