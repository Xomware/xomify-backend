"""
XOMIFY Group Members DynamoDB Helpers
=====================================
Database operations for Group Memberships table.

Table Structure:
- PK: email (string)
- SK: groupId (string)
- role: "owner" | "member"
- joinedAt: timestamp

GSI:
- groupId-email-index
  - PK: groupId
  - SK: email
"""

from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import GROUP_MEMBERS_TABLE_NAME, GROUPS_TABLE_NAME

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def add_group_member(email: str, group_id: str, role: str = "member"):
    try:
        client = boto3.client("dynamodb")

        client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": GROUP_MEMBERS_TABLE_NAME,
                        "Item": {
                            "email": {"S": email},
                            "groupId": {"S": group_id},
                            "role": {"S": role},
                            "joinedAt": {"S": _get_timestamp()}
                        }
                    }
                },
                {
                    "Update": {
                        "TableName": GROUPS_TABLE_NAME,
                        "Key": {"groupId": {"S": group_id}},
                        "UpdateExpression": "ADD memberCount :inc",
                        "ExpressionAttributeValues": {":inc": {"N": "1"}}
                    }
                }
            ]
        )

        log.info(f"{email} added to group {group_id}")
        return True

    except Exception as err:
        log.error(f"Add Group Member failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="add_group_member",
            table=GROUP_MEMBERS_TABLE_NAME
        )


def remove_group_member(email: str, group_id: str):
    try:
        client = boto3.client("dynamodb")

        client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": GROUP_MEMBERS_TABLE_NAME,
                        "Key": {"email": {"S": email}, "groupId": {"S": group_id}}
                    }
                },
                {
                    "Update": {
                        "TableName": GROUPS_TABLE_NAME,
                        "Key": {"groupId": {"S": group_id}},
                        "UpdateExpression": "ADD memberCount :dec",
                        "ExpressionAttributeValues": {":dec": {"N": "-1"}}
                    }
                }
            ]
        )

        log.info(f"{email} removed from group {group_id}")
        return True

    except Exception as err:
        log.error(f"Remove Group Member failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="remove_group_member",
            table=GROUP_MEMBERS_TABLE_NAME
        )


def list_groups_for_user(email: str):
    try:
        table = dynamodb.Table(GROUP_MEMBERS_TABLE_NAME)
        res = table.query(KeyConditionExpression=Key("email").eq(email))
        return res["Items"]

    except Exception as err:
        log.error(f"List Groups For User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_groups_for_user",
            table=GROUP_MEMBERS_TABLE_NAME
        )


def list_members_of_group(group_id: str):
    try:
        table = dynamodb.Table(GROUP_MEMBERS_TABLE_NAME)
        res = table.query(
            IndexName="groupId-email-index",
            KeyConditionExpression=Key("groupId").eq(group_id)
        )
        return res["Items"]

    except Exception as err:
        log.error(f"List Members Of Group failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_members_of_group",
            table=GROUP_MEMBERS_TABLE_NAME
        )
