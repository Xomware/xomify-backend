"""
DELETE /groups/remove-song - Remove a song from group
"""

import boto3
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import get_query_params, require_fields
from lambdas.common.constants import GROUP_TRACKS_TABLE_NAME

log = get_logger(__file__)

HANDLER = 'groups_remove_song'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'email', 'groupId', 'songId')

    email = params.get('email')
    group_id = params.get('groupId')
    song_id = params.get('songId')  # This is the trackIdTimestamp (SK)

    log.info(f"User {email} removing song {song_id} from group {group_id}")

    # Delete track
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    table = dynamodb.Table(GROUP_TRACKS_TABLE_NAME)

    table.delete_item(
        Key={
            'groupId': group_id,
            'trackIdTimestamp': song_id
        }
    )

    log.info(f"Song {song_id} removed from group {group_id}")

    return {
        'statusCode': 204,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': ''
    }
