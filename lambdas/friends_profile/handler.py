"""
GET /friends/profile - Get a friend's profile with top items
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.friends_profile_helper import get_user_top_items

log = get_logger(__file__)

HANDLER = 'friends_profile'


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'friendEmail')

    friend_email = params.get('friendEmail')

    log.info(f"Getting friend's profile for user {friend_email}")
    friend_user = get_user_table_data(friend_email)
    log.info(f"Retrieved data for {friend_email}")

    friend_top_items = asyncio.run(get_user_top_items(friend_user))

    return success_response({
        'displayName': friend_user.get('displayName', None),
        'email': friend_email,
        'userId': friend_user.get('userId', None),
        'avatar': friend_user.get('avatar', None),
        'topSongs': friend_top_items['tracks'],
        'topArtists': friend_top_items['artists'],
        'topGenres': friend_top_items['genres'],
    })
