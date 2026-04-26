"""
Tests for auth_login lambda.

Covers:
- happy path mints a JWT with correct claims
- missing spotifyAccessToken in body  -> 400
- empty body                          -> 400
- empty/whitespace-only token         -> 400
- Spotify returns 401                 -> 401 structured error
- Spotify returns 200 but no email    -> 502 structured error
- Spotify returns 200 but no id       -> 502 structured error
- Spotify network failure             -> 502 structured error
"""

import json
from unittest.mock import MagicMock, patch

import jwt
import pytest

from lambdas.auth_login.handler import JWT_TTL_SECONDS, handler

TEST_SECRET = "test-api-secret-key"


def _make_event(body, source_ip: str = "203.0.113.5") -> dict:
    """Build an API Gateway event with a serialized body and a sourceIp."""
    return {
        "httpMethod": "POST",
        "path": "/auth/login",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": {},
        "isBase64Encoded": False,
        "requestContext": {
            "identity": {"sourceIp": source_ip},
        },
    }


@patch("lambdas.auth_login.handler.requests.get")
def test_happy_path_mints_jwt(mock_requests_get, mock_context):
    """Spotify /me returns email + id; handler returns a JWT with expected claims."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "email": "user@example.com",
        "id": "spotify-user-1",
        "display_name": "User Example",
    }
    mock_requests_get.return_value = mock_response

    event = _make_event({"spotifyAccessToken": "valid-spotify-token"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])

    assert "token" in body
    assert "expiresAt" in body
    assert isinstance(body["token"], str)
    assert isinstance(body["expiresAt"], str)

    # Spotify was called once with the right URL, header, and timeout.
    mock_requests_get.assert_called_once()
    args, kwargs = mock_requests_get.call_args
    assert args[0] == "https://api.spotify.com/v1/me"
    assert kwargs["headers"]["Authorization"] == "Bearer valid-spotify-token"
    assert kwargs["timeout"] == 5

    # Decode and assert claims.
    decoded = jwt.decode(body["token"], TEST_SECRET, algorithms=["HS256"])
    assert decoded["email"] == "user@example.com"
    assert decoded["userId"] == "spotify-user-1"
    assert isinstance(decoded["iat"], int)
    assert isinstance(decoded["exp"], int)
    assert decoded["exp"] - decoded["iat"] == JWT_TTL_SECONDS


@patch("lambdas.auth_login.handler.requests.get")
def test_missing_spotify_access_token_returns_400(mock_requests_get, mock_context):
    """Body missing spotifyAccessToken -> ValidationError -> 400."""
    event = _make_event({"somethingElse": "nope"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    assert "spotifyAccessToken" in body["error"]["message"]
    mock_requests_get.assert_not_called()


@patch("lambdas.auth_login.handler.requests.get")
def test_empty_body_returns_400(mock_requests_get, mock_context):
    """Completely empty body -> 400."""
    event = _make_event(None)

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    mock_requests_get.assert_not_called()


@patch("lambdas.auth_login.handler.requests.get")
def test_whitespace_token_returns_400(mock_requests_get, mock_context):
    """Token that is just whitespace counts as missing -> 400."""
    event = _make_event({"spotifyAccessToken": "   "})

    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    mock_requests_get.assert_not_called()


@patch("lambdas.auth_login.handler.requests.get")
def test_spotify_401_returns_401(mock_requests_get, mock_context):
    """Spotify says the token is bad -> handler returns structured 401."""
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"error": {"status": 401, "message": "Invalid access token"}}
    mock_requests_get.return_value = mock_response

    event = _make_event({"spotifyAccessToken": "expired-or-bogus-token"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error"]["status"] == 401
    assert body["error"]["handler"] == "auth_login"


@patch("lambdas.auth_login.handler.requests.get")
def test_spotify_200_missing_email_returns_502(mock_requests_get, mock_context):
    """Spotify returns 200 but no email -> 502 because upstream is malformed."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "spotify-user-1"}  # no email
    mock_requests_get.return_value = mock_response

    event = _make_event({"spotifyAccessToken": "valid-but-thin-profile"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"]["status"] == 502
    assert body["error"]["handler"] == "auth_login"


@patch("lambdas.auth_login.handler.requests.get")
def test_spotify_200_missing_id_returns_502(mock_requests_get, mock_context):
    """Spotify returns 200 but no id -> 502."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"email": "user@example.com"}  # no id
    mock_requests_get.return_value = mock_response

    event = _make_event({"spotifyAccessToken": "valid-but-thin-profile"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"]["status"] == 502


@patch("lambdas.auth_login.handler.requests.get")
def test_spotify_network_failure_returns_502(mock_requests_get, mock_context):
    """Network problems reaching Spotify surface as 502."""
    import requests as _requests

    mock_requests_get.side_effect = _requests.ConnectionError("boom")

    event = _make_event({"spotifyAccessToken": "any-token"})

    response = handler(event, mock_context)

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error"]["status"] == 502


@pytest.fixture(autouse=True)
def _patch_api_secret_key(monkeypatch):
    """
    Pin the JWT signing secret to a deterministic value for every test in this
    module. The conftest already injects a fake `lambdas.common.ssm_helpers`
    with API_SECRET_KEY = 'test-api-secret-key'; we re-pin here defensively
    against any test that imported the symbol before our module loaded.
    """
    import lambdas.auth_login.handler as auth_login_handler

    monkeypatch.setattr(auth_login_handler, "API_SECRET_KEY", TEST_SECRET, raising=False)
    yield
