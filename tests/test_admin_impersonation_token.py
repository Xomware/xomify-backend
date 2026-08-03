"""
Tests for GET /admin/impersonation-token (admin-only Spotify access-token mint).

Admin email is `admin@example.com` (conftest). Non-admin uses the default
`test@example.com` identity.

The endpoint reuses `Spotify.get_access_token` (invoked by the sync
constructor) to exchange the target user's stored refresh token for a fresh
short-lived access token, so the tests patch the `Spotify` client the handler
imports rather than making real HTTP calls.
"""

import json
from unittest.mock import MagicMock, patch

ADMIN = "admin@example.com"
NON_ADMIN = "test@example.com"


def _spotify_stub(access_token="fresh-access-token", expires_in=3600):
    """Build a Spotify() replacement that mimics the sync-constructed client."""
    def _factory(user, session=None):
        stub = MagicMock()
        stub.access_token = access_token
        stub.token_expires_in = expires_in
        return stub
    return _factory


@patch("lambdas.admin_impersonation_token.handler.Spotify")
@patch("lambdas.admin_impersonation_token.handler.get_user_table_data")
def test_impersonation_token_happy(mock_user, mock_spotify,
                                   authorized_event, mock_context):
    from lambdas.admin_impersonation_token.handler import handler

    mock_user.return_value = {"email": "u@x.com", "userId": "sp1",
                              "refreshToken": "target-refresh-tok"}
    mock_spotify.side_effect = _spotify_stub("fresh-access-token", 3600)

    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"email": "u@x.com"})
    resp = handler(event, mock_context)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"accessToken": "fresh-access-token", "expiresIn": 3600}

    # The client is built from the TARGET user's row (their refresh token).
    built_user = mock_spotify.call_args.args[0]
    assert built_user["refreshToken"] == "target-refresh-tok"
    # Refresh token is never returned.
    assert "refreshToken" not in body


@patch("lambdas.admin_impersonation_token.handler.Spotify")
@patch("lambdas.admin_impersonation_token.handler.get_user_table_data")
def test_impersonation_token_defaults_expiry(mock_user, mock_spotify,
                                             authorized_event, mock_context):
    from lambdas.admin_impersonation_token.handler import handler

    mock_user.return_value = {"email": "u@x.com", "refreshToken": "tok"}
    # Spotify omitted expires_in -> handler falls back to 3600.
    mock_spotify.side_effect = _spotify_stub("tok-access", None)

    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"email": "u@x.com"})
    resp = handler(event, mock_context)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["expiresIn"] == 3600


def test_impersonation_token_non_admin_403(authorized_event, mock_context):
    from lambdas.admin_impersonation_token.handler import handler

    with patch("lambdas.admin_impersonation_token.handler.get_user_table_data") as mock_user, \
         patch("lambdas.admin_impersonation_token.handler.Spotify") as mock_spotify:
        event = authorized_event(email=NON_ADMIN, httpMethod="GET",
                                 queryStringParameters={"email": "u@x.com"})
        resp = handler(event, mock_context)

    assert resp["statusCode"] == 403
    # Non-admins never reach the lookup or token mint.
    mock_user.assert_not_called()
    mock_spotify.assert_not_called()


def test_impersonation_token_missing_email_400(authorized_event, mock_context):
    from lambdas.admin_impersonation_token.handler import handler

    resp = handler(authorized_event(email=ADMIN, httpMethod="GET",
                                    queryStringParameters={}), mock_context)
    assert resp["statusCode"] == 400


@patch("lambdas.admin_impersonation_token.handler.Spotify")
@patch("lambdas.admin_impersonation_token.handler.get_user_table_data")
def test_impersonation_token_unknown_user_404(mock_user, mock_spotify,
                                              authorized_event, mock_context):
    from lambdas.admin_impersonation_token.handler import handler
    from lambdas.common.errors import NotFoundError

    mock_user.side_effect = NotFoundError(message="nope", resource="u@x.com")

    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"email": "u@x.com"})
    resp = handler(event, mock_context)

    assert resp["statusCode"] == 404
    mock_spotify.assert_not_called()


@patch("lambdas.admin_impersonation_token.handler.Spotify")
@patch("lambdas.admin_impersonation_token.handler.get_user_table_data")
def test_impersonation_token_no_refresh_token_404(mock_user, mock_spotify,
                                                  authorized_event, mock_context):
    from lambdas.admin_impersonation_token.handler import handler

    # Target exists but never connected Spotify.
    mock_user.return_value = {"email": "u@x.com", "userId": "sp1"}

    event = authorized_event(email=ADMIN, httpMethod="GET",
                             queryStringParameters={"email": "u@x.com"})
    resp = handler(event, mock_context)

    assert resp["statusCode"] == 404
    mock_spotify.assert_not_called()
