"""
XOMIFY Track Ratings DynamoDB Helpers
=====================================
Database operations for Track Ratings table.

Table Structure:
- PK: email (string - Spotify track ID)
- SK: trackId (string)
- rating: number (1.0, 1.5, 2.0, ... 5.0)
- ratedAt: string (timestamp)
// Denormalized for easy display without Spotify lookups:
- trackName: string
- artistName: string
- albumArt: string
- albumName?: string
- context?: string ("friend_profile" | "top_songs" | "queue" | "modal")
"""

from datetime import datetime, timezone, timedelta
import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.logger import get_logger
from lambdas.common.errors import DynamoDBError
from lambdas.common.constants import TRACK_RATINGS_TABLE_NAME

log = get_logger(__file__)

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb", region_name="us-east-1")


def _get_timestamp() -> str:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

# ============================================
# List All Track Ratings for User
# ============================================
def list_all_track_ratings_for_user(email: str):
    try:
        log.info(f"Searching Track Ratings table for all ratings for {email}..")
        table = dynamodb.Table(TRACK_RATINGS_TABLE_NAME)
        response = table.query(
            KeyConditionExpression=Key("email").eq(email)
        )

        items = response["Items"]
        return items
    except Exception as err:
        log.error(f"List All Track Ratings for User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="list_all_track_ratings_for_user",
            table=TRACK_RATINGS_TABLE_NAME
        )

# ============================================
# Get Single Track Rating for User
# ============================================
def get_single_track_rating_for_user(email: str, track_id: str):
    try:
        log.info(
            f"Fetching Track Rating for email {email} and track id {track_id}.."
        )
        table = dynamodb.Table(TRACK_RATINGS_TABLE_NAME)

        response = table.get_item(
            Key={
                "email": email,
                "trackId": track_id
            }
        )

        item = response.get("Item")
        if not item:
            log.info(f"No rating found for email {email} and track id {track_id}")
            return {}

        return item

    except Exception as err:
        log.error(f"Get Single Track Rating for User failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_single_track_rating_for_user",
            table=TRACK_RATINGS_TABLE_NAME
        )
    
# ============================================
# Create or Update Track Rating
# ============================================
def upsert_track_rating(
    email: str,
    track_id: str,
    rating: float,
    track_name: str,
    artist_name: str,
    album_art: str,
    album_name: str | None = None,
    context: str | None = None,
):
    try:
        # Validate rating range
        if rating < 1.0 or rating > 5.0:
            raise ValueError("Rating must be between 1.0 and 5.0")

        log.info(
            f"Upserting Track Rating: email {email}, track_id {track_id}"
        )

        table = dynamodb.Table(TRACK_RATINGS_TABLE_NAME)

        update_expression = """
            SET rating = :rating,
                ratedAt = :ratedAt,
                trackName = :trackName,
                artistName = :artistName,
                albumArt = :albumArt
        """

        expression_values = {
            ":rating": rating,
            ":ratedAt": _get_timestamp(),
            ":trackName": track_name,
            ":artistName": artist_name,
            ":albumArt": album_art,
        }

        if album_name is not None:
            update_expression += ", albumName = :albumName"
            expression_values[":albumName"] = album_name

        if context is not None:
            update_expression += ", context = :context"
            expression_values[":context"] = context

        response = table.update_item(
            Key={
                "email": email,
                "trackId": track_id,
            },
            UpdateExpression=update_expression,
            ExpressionAttributeValues=expression_values,
            ReturnValues="ALL_NEW",
        )

        return response["Attributes"]

    except Exception as err:
        log.error(f"Upsert Track Rating failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="upsert_track_rating",
            table=TRACK_RATINGS_TABLE_NAME,
        )
    
# ============================================
# Delete Track Rating
# ============================================
def delete_track_rating(email: str, track_id: str) -> bool:
    try:
        log.info(
            f"Deleting Track Rating: email {email}, trackId {track_id}"
        )

        table = dynamodb.Table(TRACK_RATINGS_TABLE_NAME)

        table.delete_item(
            Key={
                "email": email,
                "trackId": track_id,
            },
            ConditionExpression="attribute_exists(email)",
        )

        return True

    except table.meta.client.exceptions.ConditionalCheckFailedException:
        log.warning(
            f"No Track Rating found to delete for email {email}, trackId {track_id}"
        )
        return False

    except Exception as err:
        log.error(f"Delete Track Rating failed: {err}")
        raise DynamoDBError(
            message=str(err),
            function="delete_track_rating",
            table=TRACK_RATINGS_TABLE_NAME,
        )
