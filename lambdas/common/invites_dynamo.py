"""
XOMIFY Invites DynamoDB Helpers
===============================
Database operations for the xomify-invites table.

Table Structure:
- PK: inviteCode (string, 8-char base32)

Attributes:
- senderEmail: string
- createdAt: ISO8601 UTC timestamp
- expiresAt: ISO8601 UTC timestamp (30 days after createdAt by default)
- consumedAt: ISO8601 UTC timestamp or absent
- consumedBy: string (consumer email) or absent
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import INVITES_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

INVITE_TTL_DAYS = 30
INVITE_CODE_LEN = 8
MAX_OUTSTANDING_INVITES_PER_SENDER = 10


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def generate_invite_code() -> str:
    """Generate an 8-char uppercase base32 invite code."""
    # 5 random bytes -> 8 chars of base32 (no padding needed)
    return base64.b32encode(os.urandom(5)).decode("ascii")[:INVITE_CODE_LEN].upper()


# ============================================
# Create Invite
# ============================================
def create_invite(
    sender_email: str,
    invite_code: str,
    ttl_days: int = INVITE_TTL_DAYS,
) -> dict[str, Any]:
    """PutItem with attribute_not_exists(inviteCode) — raises on collision."""
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)
        created_at = _iso_now()
        expires_at = _iso_future(ttl_days)

        item = {
            "inviteCode": invite_code,
            "senderEmail": sender_email,
            "createdAt": created_at,
            "expiresAt": expires_at,
        }

        table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(inviteCode)",
        )
        log.info(f"Invite {invite_code} created by {sender_email}")
        return item

    except ClientError as err:
        # Surface collision so callers can retry with a new code
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise
        log.error(f"Create Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_invite",
            table=INVITES_TABLE_NAME,
        )
    except Exception as err:
        log.error(f"Create Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_invite",
            table=INVITES_TABLE_NAME,
        )


# ============================================
# Get Invite
# ============================================
def get_invite(invite_code: str) -> Optional[dict[str, Any]]:
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)
        response = table.get_item(Key={"inviteCode": invite_code})
        return response.get("Item")
    except Exception as err:
        log.error(f"Get Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_invite",
            table=INVITES_TABLE_NAME,
        )


# ============================================
# Consume Invite (atomic)
# ============================================
def consume_invite(invite_code: str, recipient_email: str) -> dict[str, Any]:
    """
    Atomic update: set consumedAt + consumedBy only when the invite is still
    unconsumed and unexpired. Raises ClientError (ConditionalCheckFailedException)
    if the invite was already consumed or expired — caller maps to 410.
    """
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)
        now_iso = _iso_now()

        response = table.update_item(
            Key={"inviteCode": invite_code},
            UpdateExpression="SET consumedAt = :now, consumedBy = :email",
            ConditionExpression="attribute_not_exists(consumedAt) AND expiresAt > :now",
            ExpressionAttributeValues={
                ":now": now_iso,
                ":email": recipient_email,
            },
            ReturnValues="ALL_NEW",
        )
        log.info(f"Invite {invite_code} consumed by {recipient_email}")
        return response.get("Attributes", {})

    except ClientError as err:
        if err.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise
        log.error(f"Consume Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="consume_invite",
            table=INVITES_TABLE_NAME,
        )
    except Exception as err:
        log.error(f"Consume Invite failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="consume_invite",
            table=INVITES_TABLE_NAME,
        )


# ============================================
# List Invites By Sender
# ============================================
def list_invites_by_sender(
    sender_email: str,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Return invites issued by a sender. Uses Scan + FilterExpression because the
    invites table has no sender GSI in v1 (flagged for follow-up once traffic grows).

    Args:
        sender_email: sender to match
        active_only: when True, return only invites that are neither consumed nor expired
    """
    try:
        table = dynamodb.Table(INVITES_TABLE_NAME)
        now_iso = _iso_now()

        filter_expr = Attr("senderEmail").eq(sender_email)
        if active_only:
            filter_expr = (
                filter_expr
                & Attr("consumedAt").not_exists()
                & Attr("expiresAt").gt(now_iso)
            )

        items: list[dict[str, Any]] = []
        scan_kwargs: dict[str, Any] = {"FilterExpression": filter_expr}
        while True:
            response = table.scan(**scan_kwargs)
            items.extend(response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                break
            scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

        return items

    except Exception as err:
        log.error(f"List Invites By Sender failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_invites_by_sender",
            table=INVITES_TABLE_NAME,
        )


def count_outstanding_invites_for_sender(sender_email: str) -> int:
    """Rate-limit helper — count of non-consumed, non-expired invites for a sender."""
    return len(list_invites_by_sender(sender_email, active_only=True))
