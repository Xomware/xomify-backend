"""Tests for the auth_spotify_token and auth_spotify_refresh lambdas."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from lambdas.auth_spotify_refresh.handler import handler as refresh_handler
from lambdas.auth_spotify_token.handler import handler as token_handler

TOKENS = {
    "access_token": "new-access",
    "token_type": "Bearer",
    "expires_in": 3600,
    "refresh_token": "new-refresh",
    "scope": "user-read-email",
}


def _event(body) -> dict:
    return {"httpMethod": "POST", "body": json.dumps(body), "headers": {}, "requestContext": {}}


def _spotify(status: int, payload: dict) -> MagicMock:
    response = MagicMock(status_code=status, text=json.dumps(payload))
    response.json.return_value = payload
    return response


@patch("lambdas.common.spotify_token.requests.post")
def test_code_exchange_adds_client_credentials(mock_post, mock_context):
    mock_post.return_value = _spotify(200, TOKENS)

    response = token_handler(_event({"code": "abc", "redirectUri": "https://xomify.xomware.com/callback"}), mock_context)

    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == TOKENS
    sent = mock_post.call_args.kwargs["data"]
    assert sent == {
        "grant_type": "authorization_code",
        "code": "abc",
        "redirect_uri": "https://xomify.xomware.com/callback",
        "client_id": "test-spotify-client-id",
        "client_secret": "test-spotify-client-secret",
    }


@patch("lambdas.common.spotify_token.requests.post")
def test_refresh_adds_client_credentials(mock_post, mock_context):
    mock_post.return_value = _spotify(200, TOKENS)

    response = refresh_handler(_event({"refreshToken": "old-refresh"}), mock_context)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["access_token"] == "new-access"
    sent = mock_post.call_args.kwargs["data"]
    assert sent["grant_type"] == "refresh_token"
    assert sent["refresh_token"] == "old-refresh"
    assert sent["client_secret"] == "test-spotify-client-secret"


@pytest.mark.parametrize(
    "handler,body",
    [
        (token_handler, {"redirectUri": "https://xomify.xomware.com/callback"}),
        (token_handler, {"code": "abc"}),
        (token_handler, {"code": "  ", "redirectUri": "x"}),
        (refresh_handler, {}),
        (refresh_handler, {"refreshToken": ""}),
    ],
)
@patch("lambdas.common.spotify_token.requests.post")
def test_missing_fields_are_400_and_never_reach_spotify(mock_post, handler, body, mock_context):
    response = handler(_event(body), mock_context)

    assert response["statusCode"] == 400
    mock_post.assert_not_called()


@patch("lambdas.common.spotify_token.requests.post")
def test_invalid_grant_is_401(mock_post, mock_context):
    mock_post.return_value = _spotify(400, {"error": "invalid_grant", "error_description": "Invalid refresh token"})

    response = refresh_handler(_event({"refreshToken": "revoked"}), mock_context)

    assert response["statusCode"] == 401


@patch("lambdas.common.spotify_token.requests.post")
def test_other_spotify_errors_are_not_401(mock_post, mock_context):
    mock_post.return_value = _spotify(400, {"error": "invalid_client"})

    response = token_handler(_event({"code": "abc", "redirectUri": "x"}), mock_context)

    assert response["statusCode"] not in (200, 401)


@patch("lambdas.common.spotify_token.requests.post", side_effect=requests.ConnectionError("down"))
def test_network_failure_is_not_401(mock_post, mock_context):
    response = refresh_handler(_event({"refreshToken": "r"}), mock_context)

    assert response["statusCode"] not in (200, 401)
