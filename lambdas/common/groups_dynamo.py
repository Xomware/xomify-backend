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

        item = {
            "groupId": group_id,
            "name": name,
            "createdBy": created_by,
            "createdAt": _get_timestamp(),
            "memberCount": 1
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
