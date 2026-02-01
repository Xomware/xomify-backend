"""
XOMIFY Group Tracks DynamoDB Helpers
=====================================
Database operations for Group Tracks table.

Table Structure:
- PK: groupId
- SK: trackIdTimestamp (trackId#timestamp)

Attributes:
- trackId: string
- addedBy: email
- addedAt: timestamp
- trackName: string (optional)
- artistName: string (optional)
- albumImageUrl: string (optional)
- listenedBy: set<string>  # users who have listened
"""

from datetime import datetime, timezone
import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import GROUP_TRACKS_TABLE_NAME

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


# =========================================================
# Add Track To Group
# =========================================================
def add_track_to_group(group_id: str, track_id: str, added_by: str,
                       track_name: str | None = None,
                       artist_name: str | None = None,
                       album_image_url: str | None = None):
    try:
        table = dynamodb.Table(GROUP_TRACKS_TABLE_NAME)

        timestamp = _get_timestamp()
        sk = f"{track_id}#{timestamp}"

        item = {
            "groupId": group_id,
            "trackIdTimestamp": sk,
            "trackId": track_id,
            "addedBy": added_by,
            "addedAt": timestamp,
            "listenedBy": set([added_by])  # Creator has listened
        }

        if track_name:
            item["trackName"] = track_name
        if artist_name:
            item["artistName"] = artist_name
        if album_image_url:
            item["albumImageUrl"] = album_image_url

        table.put_item(Item=item)
        log.info(f"Track {track_id} added to group {group_id}")
        return True

    except Exception as err:
        log.error(f"Add Track To Group failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="add_track_to_group",
            table=GROUP_TRACKS_TABLE_NAME
        )


# =========================================================
# List Tracks For Group
# =========================================================
def list_tracks_for_group(group_id: str, newest_first: bool = True):
    try:
        table = dynamodb.Table(GROUP_TRACKS_TABLE_NAME)

        res = table.query(
            KeyConditionExpression=Key("groupId").eq(group_id),
            ScanIndexForward=not newest_first
        )

        return res["Items"]

    except Exception as err:
        log.error(f"List Tracks For Group failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_tracks_for_group",
            table=GROUP_TRACKS_TABLE_NAME
        )


# =========================================================
# Mark Track As Listened
# =========================================================
def mark_track_as_listened(group_id: str, track_id_timestamp: str, email: str):
    try:
        table = dynamodb.Table(GROUP_TRACKS_TABLE_NAME)

        table.update_item(
            Key={
                "groupId": group_id,
                "trackIdTimestamp": track_id_timestamp
            },
            UpdateExpression="ADD listenedBy :user",
            ExpressionAttributeValues={
                ":user": set([email])
            }
        )

        log.info(f"{email} listened to {track_id_timestamp} in group {group_id}")
        return True

    except Exception as err:
        log.error(f"Mark Track As Listened failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="mark_track_as_listened",
            table=GROUP_TRACKS_TABLE_NAME
        )


# =========================================================
# List Unheard Tracks For User
# =========================================================
def list_unheard_tracks_for_user(group_id: str, email: str):
    try:
        table = dynamodb.Table(GROUP_TRACKS_TABLE_NAME)

        res = table.query(
            KeyConditionExpression=Key("groupId").eq(group_id)
        )

        unheard = [
            item for item in res["Items"]
            if "listenedBy" not in item or email not in item["listenedBy"]
        ]

        return unheard

    except Exception as err:
        log.error(f"List Unheard Tracks failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_unheard_tracks_for_user",
            table=GROUP_TRACKS_TABLE_NAME
        )


# =========================================================
# Check If Everyone Listened
# =========================================================
def has_everyone_listened(group_id: str, track_id_timestamp: str, total_members: int):
    """
    total_members should come from group.memberCount
    """
    try:
        table = dynamodb.Table(GROUP_TRACKS_TABLE_NAME)

        res = table.get_item(
            Key={
                "groupId": group_id,
                "trackIdTimestamp": track_id_timestamp
            }
        )

        item = res.get("Item", {})
        listened_by = item.get("listenedBy", set())

        return len(listened_by) >= total_members

    except Exception as err:
        log.error(f"Has Everyone Listened failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="has_everyone_listened",
            table=GROUP_TRACKS_TABLE_NAME
        )
