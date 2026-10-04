"""Calls Spotify's token endpoint with the client credentials, so clients never hold the secret."""

import requests

from lambdas.common.errors import AuthorizationError, SpotifyAPIError
from lambdas.common.ssm_helpers import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_TIMEOUT_SECONDS = 10


def request_spotify_token(fields: dict, handler: str) -> dict:
    """POST `fields` plus the client credentials; return Spotify's token JSON unchanged."""
    try:
        response = requests.post(
            SPOTIFY_TOKEN_URL,
            data={**fields, "client_id": SPOTIFY_CLIENT_ID, "client_secret": SPOTIFY_CLIENT_SECRET},
            timeout=SPOTIFY_TIMEOUT_SECONDS,
        )
    except requests.RequestException as err:
        raise SpotifyAPIError(
            message=f"Failed to reach Spotify token endpoint: {err}",
            handler=handler,
            function="request_spotify_token",
            endpoint="/api/token",
        ) from err

    # invalid_grant is the client's problem (expired code, revoked refresh token):
    # 401 tells it to send the user back through login.
    if response.status_code == 400 and response.json().get("error") == "invalid_grant":
        raise AuthorizationError(
            message="Spotify rejected the code or refresh token.",
            handler=handler,
            function="request_spotify_token",
        )
    if response.status_code != 200:
        raise SpotifyAPIError(
            message=f"Spotify token endpoint returned {response.status_code}: {response.text[:200]}",
            handler=handler,
            function="request_spotify_token",
            endpoint="/api/token",
        )
    return response.json()
