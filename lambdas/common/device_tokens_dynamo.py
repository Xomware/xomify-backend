"""
XOMIFY Device Tokens DynamoDB Helpers
=====================================
Database operations for the xomify-device-tokens table.

Table Structure:
- PK: email (string)
- SK: deviceToken (string)

Attributes:
- email / deviceToken (keys)
- platform: "ios" (only platform supported in v1)
- digestEnabled: bool (opt-in for weekly digest pushes)
- queueNotificationsEnabled: bool (opt-in for threshold "N friends queued" pushes)
- createdAt / updatedAt: ISO8601 UTC timestamps
- ttl: int (epoch seconds — DynamoDB TTL auto-prunes dormant tokens after ~180 days)
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Iterable, Iterator, Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import DEVICE_TOKENS_TABLE_NAME

log = get_logger(__file__)

dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

TOKEN_TTL_DAYS = 180
DEFAULT_PLATFORM = "ios"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl_epoch(days: int = TOKEN_TTL_DAYS) -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=days)).timestamp())


# ============================================
# Upsert Token
# ============================================
def upsert_token(
    email: str,
    device_token: str,
    digest_enabled: bool = True,
    queue_notifications_enabled: bool = True,
    platform: str = DEFAULT_PLATFORM,
) -> dict[str, Any]:
    """Create or update a device-token row. Idempotent."""
    try:
        table = dynamodb.Table(DEVICE_TOKENS_TABLE_NAME)
        now_iso = _iso_now()

        response = table.update_item(
            Key={"email": email, "deviceToken": device_token},
            UpdateExpression=(
                "SET #platform = :platform, "
                "#digestEnabled = :digestEnabled, "
                "#queueNotificationsEnabled = :queueNotificationsEnabled, "
                "#updatedAt = :now, "
                "#ttl = :ttl, "
                "#createdAt = if_not_exists(#createdAt, :now)"
            ),
            ExpressionAttributeNames={
                "#platform": "platform",
                "#digestEnabled": "digestEnabled",
                "#queueNotificationsEnabled": "queueNotificationsEnabled",
                "#updatedAt": "updatedAt",
                "#ttl": "ttl",
                "#createdAt": "createdAt",
            },
            ExpressionAttributeValues={
                ":platform": platform,
                ":digestEnabled": digest_enabled,
                ":queueNotificationsEnabled": queue_notifications_enabled,
                ":now": now_iso,
                ":ttl": _ttl_epoch(),
            },
            ReturnValues="ALL_NEW",
        )
        log.info(f"Device token upserted for {email} (platform={platform})")
        return response.get("Attributes", {})
    except Exception as err:
        log.error(f"Upsert Token failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="upsert_token",
            table=DEVICE_TOKENS_TABLE_NAME,
        )


# ============================================
# Delete Token
# ============================================
def delete_token(email: str, device_token: str) -> bool:
    try:
        table = dynamodb.Table(DEVICE_TOKENS_TABLE_NAME)
        table.delete_item(Key={"email": email, "deviceToken": device_token})
        log.info(f"Device token deleted for {email}")
        return True
    except Exception as err:
        log.error(f"Delete Token failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_token",
            table=DEVICE_TOKENS_TABLE_NAME,
        )


# ============================================
# List Tokens For User
# ============================================
def list_tokens_for_user(email: str) -> list[dict[str, Any]]:
    try:
        table = dynamodb.Table(DEVICE_TOKENS_TABLE_NAME)
        response = table.query(KeyConditionExpression=Key("email").eq(email))
        return response.get("Items", [])
    except Exception as err:
        log.error(f"List Tokens For User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_tokens_for_user",
            table=DEVICE_TOKENS_TABLE_NAME,
        )


# ============================================
# Scan Tokens For Digest
# ============================================
def scan_tokens_for_digest() -> Iterator[dict[str, Any]]:
    """
    Paginated scan of tokens with digestEnabled=true. Yields rows as they
    are found so callers can batch-process without holding the full result
    set in memory. At v1 user counts this scan is fine; a GSI on
    digestEnabled should be added if the scan starts to cost real money.
    """
    try:
        table = dynamodb.Table(DEVICE_TOKENS_TABLE_NAME)
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": Attr("digestEnabled").eq(True),
        }
        while True:
            response = table.scan(**scan_kwargs)
            for item in response.get("Items", []):
                yield item
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            scan_kwargs["ExclusiveStartKey"] = last_key
    except Exception as err:
        log.error(f"Scan Tokens For Digest failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="scan_tokens_for_digest",
            table=DEVICE_TOKENS_TABLE_NAME,
        )


# ============================================
# Group by email helper
# ============================================
def group_tokens_by_email(tokens: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Collapse multi-device rows into {email: [tokens]}."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for tok in tokens:
        email = tok.get("email")
        if not email:
            continue
        grouped.setdefault(email, []).append(tok)
    return grouped
