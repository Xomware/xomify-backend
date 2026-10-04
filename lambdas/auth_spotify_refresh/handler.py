"""
POST /auth/spotify-refresh - Trade a Spotify refresh token for a new access token.

Public route (no authorizer): the client refreshes before it can mint a Xomify JWT.
Holding the refresh token is the credential.
"""

from typing import Any

from lambdas.common.errors import ValidationError, handle_errors
from lambdas.common.spotify_token import request_spotify_token
from lambdas.common.utility_helpers import parse_body, success_response

HANDLER = "auth_spotify_refresh"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    refresh_token = parse_body(event).get("refreshToken")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise ValidationError(
            message="Missing required field: refreshToken",
            handler=HANDLER,
            function="handler",
            field="refreshToken",
        )

    tokens = request_spotify_token({"grant_type": "refresh_token", "refresh_token": refresh_token}, HANDLER)
    return success_response(tokens)
