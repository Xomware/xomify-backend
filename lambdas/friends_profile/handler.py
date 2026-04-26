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
from lambdas.common.utility_helpers import (
    success_response,
    get_query_params,
    require_fields,
    get_caller_email,
)
from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.friends_profile_helper import get_user_top_items, get_user_public_playlists
from lambdas.common.shares_dynamo import count_shares_for_user
from lambdas.common.user_likes_dynamo import get_likes_settings

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


def _safe_likes_settings(friend_email: str) -> dict | None:
    """Return ``{likes_count, likes_public}`` for friend, or None on failure.

    Mirrors ``_safe_share_count`` semantics: failures degrade the field
    to absent rather than 500ing the whole profile request.
    """
    try:
        return get_likes_settings(friend_email)
    except Exception as err:
        log.warning(f"likesSettings lookup failed for {friend_email}: {err}")
        return None


def _safe_caller_email(event) -> str | None:
    """Resolve the caller's email or return None if it can't be determined.

    The friends_profile endpoint should not 401 just because we couldn't
    resolve the caller — the privacy gate falls open to "treat as
    non-self" (i.e. we honour ``likes_public``) which is the safer
    default for a read-only profile lookup.
    """
    try:
        return get_caller_email(event)
    except Exception as err:
        log.warning(f"caller-email resolution failed in friends_profile: {err}")
        return None


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    require_fields(params, 'friendEmail')

    friend_email = params.get('friendEmail')
    caller_email = _safe_caller_email(event)

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

    # likesCount enrichment — honour the target's privacy flag. We only
    # include the field when:
    #   - the lookup succeeded, AND
    #   - the target has likes_public=True OR the caller is the target.
    # Otherwise the field is omitted (iOS treats absence as "unknown" and
    # hides the chip, matching the contract for shareCount/playlistCount).
    likes_settings = _safe_likes_settings(friend_email)
    if likes_settings is not None:
        is_self = caller_email is not None and caller_email == friend_email
        if is_self or likes_settings.get('likes_public', True):
            payload['likesCount'] = int(likes_settings.get('likes_count', 0))

    return success_response(payload)
