"""
XOMIFY Groups DynamoDB Helpers
=====================================
Database operations for Groups table.

Table Structure:
- PK: groupId (string/uuid)
- name: string
- createdBy: email
- createdAt: timestamp
- imageUrl: string (optional)
- memberCount: number (optional, cached)
"""

from datetime import datetime, timezone
import boto3

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import GROUPS_TABLE_NAME

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def create_group(group_id: str, name: str, created_by: str, image_url: str | None = None):
    try:
        table = dynamodb.Table(GROUPS_TABLE_NAME)

        # Seed memberCount at 0 — groups_create calls add_group_member for
        # the owner immediately after, which atomically increments this to 1.
        # Seeding at 1 previously caused an off-by-one (every group started at 2).
        item = {
            "groupId": group_id,
            "name": name,
            "createdBy": created_by,
            "createdAt": _get_timestamp(),
            "memberCount": 0
        }

        if image_url:
            item["imageUrl"] = image_url

        table.put_item(Item=item)
        log.info(f"Group created: {group_id}")
        return True

    except Exception as err:
        log.error(f"Create Group failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="create_group",
            table=GROUPS_TABLE_NAME
        )


def get_group(group_id: str):
    try:
        table = dynamodb.Table(GROUPS_TABLE_NAME)
        res = table.get_item(Key={"groupId": group_id})
        return res.get("Item")

    except Exception as err:
        log.error(f"Get Group failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_group",
            table=GROUPS_TABLE_NAME
        )


def batch_get_groups(group_ids: list[str]) -> list[dict]:
    """
    Fetch multiple Group items in chunks of 100 (DynamoDB BatchGetItem
    limit). Missing IDs are simply absent from the returned list — callers
    should handle the membership → group join upstream.
    """
    if not group_ids:
        return []

    client = boto3.client("dynamodb", region_name="us-east-1")
    out: list[dict] = []

    # BatchGetItem caps at 100 keys per call. We deduplicate first to avoid
    # wasted throughput when a user has duplicate membership rows.
    unique_ids = list({gid for gid in group_ids if gid})

    for i in range(0, len(unique_ids), 100):
        chunk = unique_ids[i:i + 100]
        try:
            res = client.batch_get_item(
                RequestItems={
                    GROUPS_TABLE_NAME: {
                        "Keys": [{"groupId": {"S": gid}} for gid in chunk]
                    }
                }
            )
            raw_items = res.get("Responses", {}).get(GROUPS_TABLE_NAME, [])
            for raw in raw_items:
                out.append(_deserialize_item(raw))
        except Exception as err:
            log.error(f"Batch Get Groups failed: {err}")
            raise DynamoDBError(
                message=str(err),
                function="batch_get_groups",
                table=GROUPS_TABLE_NAME
            )

    return out


def _deserialize_item(raw: dict) -> dict:
    """Unwrap DynamoDB low-level attribute format to plain dict."""
    out: dict = {}
    for key, val in raw.items():
        if "S" in val:
            out[key] = val["S"]
        elif "N" in val:
            try:
                out[key] = int(val["N"])
            except ValueError:
                out[key] = float(val["N"])
        elif "BOOL" in val:
            out[key] = val["BOOL"]
        elif "NULL" in val:
            out[key] = None
    return out
