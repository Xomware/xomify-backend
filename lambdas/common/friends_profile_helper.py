import aiohttp
from lambdas.common.spotify import Spotify
from lambdas.common.logger import get_logger

log = get_logger(__file__)


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