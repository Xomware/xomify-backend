"""
POST /auth/spotify-token - Exchange a Spotify authorization code for tokens.

Public route (no authorizer): the caller has no session yet. Spotify itself rejects a
redirect_uri that isn't registered on the app.
"""

from typing import Any

from lambdas.common.errors import ValidationError, handle_errors
from lambdas.common.spotify_token import request_spotify_token
from lambdas.common.utility_helpers import parse_body, success_response

HANDLER = "auth_spotify_token"


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    body = parse_body(event)
    for field in ("code", "redirectUri"):
        if not isinstance(body.get(field), str) or not body[field].strip():
            raise ValidationError(
                message=f"Missing required field: {field}",
                handler=HANDLER,
                function="handler",
                field=field,
            )

    tokens = request_spotify_token(
        {"grant_type": "authorization_code", "code": body["code"], "redirect_uri": body["redirectUri"]},
        HANDLER,
    )
    return success_response(tokens)
