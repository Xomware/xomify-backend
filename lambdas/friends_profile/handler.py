"""
GET /friends/profile - Get a friend's profile with top items.

Response shape is pinned by `docs/ios-profile-redesign-contract.md`. The
iOS client (`FriendProfile` in `Models/SocialModels.swift`) treats every
non-id field as optional, so a partial payload (e.g. shareCount lookup
fails) still decodes — we just leave the count out instead of 500ing.
"""

import asyncio
from lambdas.common.logger import get_logger
from lambdas.common.errors import handle_errors
from lambdas.common.utility_helpers import success_response, get_query_params, require_fields
from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.friends_profile_helper import get_user_top_items, get_user_public_playlists
from lambdas.common.shares_dynamo import count_shares_for_user

log = get_logger(__file__)

HANDLER = 'friends_profile'


async def _gather_profile(friend_user: dict) -> dict:
    """Fetch top items and public playlists concurrently."""
    top_items_task = get_user_top_items(friend_user)
    playlists_task = get_user_public_playlists(friend_user)
    top_items, playlists = await asyncio.gather(top_items_task, playlists_task)
    return {'top_items': top_items, 'playlists': playlists}


def _safe_share_count(friend_email: str) -> int | None:
    """Return total shares authored by friend, or None on lookup failure.

    A DDB hiccup on the count query must not break the whole profile —
    the iOS header just hides the share-count chip when the field is
    absent.
    """
    try:
        return count_shares_for_user(friend_email)
    except Exception as err:
        log.warning(f"shareCount lookup failed for {friend_email}: {err}")
        return None


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'friendEmail')

    friend_email = params.get('friendEmail')

    log.info(f"Getting friend's profile for user {friend_email}")
    friend_user = get_user_table_data(friend_email)
    log.info(f"Retrieved data for {friend_email}")

    result = asyncio.run(_gather_profile(friend_user))
    friend_top_items = result['top_items']
    friend_playlists = result['playlists']

    share_count = _safe_share_count(friend_email)
    playlist_count = len(friend_playlists) if friend_playlists is not None else None

    payload = {
        'displayName': friend_user.get('displayName', None),
        'email': friend_email,
        'userId': friend_user.get('userId', None),
        'avatar': friend_user.get('avatar', None),
        'topSongs': friend_top_items['tracks'],
        'topArtists': friend_top_items['artists'],
        'topGenres': friend_top_items['genres'],
        'playlists': friend_playlists,
        'playlistCount': playlist_count,
    }
    if share_count is not None:
        payload['shareCount'] = share_count

    return success_response(payload)
