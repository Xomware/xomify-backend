import aiohttp
from lambdas.common.spotify import Spotify
from lambdas.common.aiohttp_helper import fetch_json
from lambdas.common.logger import get_logger

log = get_logger(__file__)

SPOTIFY_BASE_URL = "https://api.spotify.com/v1"
PUBLIC_PLAYLISTS_LIMIT = 50


async def get_user_top_items(user: dict) -> dict:
    """
    Fetch a user's top tracks, artists, and genres from Spotify.

    Args:
        user: User dict containing email, userId, refreshToken

    Returns:
        Dict with tracks, artists, and genres for each time range

    Raises:
        Exception: If Spotify API calls fail
    """
    try:
        log.info(f"Getting user top items via API for user {user.get('email', 'unknown')}")

        async with aiohttp.ClientSession() as session:
            spotify = Spotify(user, session)
            await spotify.aiohttp_initialize_top_items()
            top_items = await spotify.get_top_items_for_api()

            log.info(f"Successfully retrieved top items for user {user.get('email', 'unknown')}")
            return top_items

    except Exception as err:
        log.error(f"Get User Top Items: {err}")
        raise Exception(f"Get User Top Items: {err}") from err


async def get_user_public_playlists(user: dict) -> list:
    """
    Fetch a user's *public* playlists (ones they own and marked public).

    Called via the target user's own access token. `/me/playlists` returns
    followed playlists too — we filter to `public=True AND owner.id == user_id`
    so the friend profile only shows playlists they authored publicly.

    Returns a slim list of dicts ready to embed in the friend-profile
    response: `id, name, description, imageUrl, trackCount, uri, externalUrl`.
    On any error, returns an empty list so the profile still renders.
    """
    try:
        user_id = user.get('userId', '')
        log.info(f"Fetching public playlists for user {user.get('email', 'unknown')} (id={user_id})")

        async with aiohttp.ClientSession() as session:
            spotify = Spotify(user, session)
            access_token = await spotify.aiohttp_get_access_token()
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            url = f"{SPOTIFY_BASE_URL}/me/playlists?limit={PUBLIC_PLAYLISTS_LIMIT}"
            data = await fetch_json(session, url, headers=headers)

            items = data.get('items', []) or []

            slim = []
            for p in items:
                if not p:
                    continue
                if not p.get('public'):
                    continue
                owner = p.get('owner') or {}
                if owner.get('id') != user_id:
                    continue

                images = p.get('images') or []
                image_url = images[0].get('url') if images else None
                tracks = p.get('tracks') or {}

                slim.append({
                    'id': p.get('id'),
                    'name': p.get('name'),
                    'description': p.get('description') or '',
                    'imageUrl': image_url,
                    'trackCount': tracks.get('total', 0),
                    'uri': p.get('uri'),
                    'externalUrl': (p.get('external_urls') or {}).get('spotify')
                })

            log.info(f"Returning {len(slim)} public playlists for {user.get('email', 'unknown')}")
            return slim

    except Exception as err:
        # Don't fail the whole friend profile just because playlists failed
        log.error(f"Get User Public Playlists: {err}")
        return []