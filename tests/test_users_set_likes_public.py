"""
Tests for the /users/likes-public lambda.

Covers:
- Happy path: caller sets their own flag.
- Cross-user toggle rejected with 401.
- Missing fields -> 400.
- Non-bool value -> 400.
- Stringy bool ("true"/"false") accepted.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.users_set_likes_public.handler import handler


def _event(authorized_event, *, body: dict, caller="user@example.com"):
    return authorized_event(
        email=caller,
        httpMethod="POST",
        path="/users/likes-public",
        body=json.dumps(body),
    )


@patch("lambdas.users_set_likes_public.handler.set_likes_public")
def test_happy_path_sets_value(mock_set, mock_context, authorized_event):
    mock_set.return_value = False
    event = _event(authorized_event, body={"email": "user@example.com", "value": False})

    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {"email": "user@example.com", "likesPublic": False}
    mock_set.assert_called_once_with("user@example.com", False)


@patch("lambdas.users_set_likes_public.handler.set_likes_public")
def test_cross_user_toggle_rejected(mock_set, mock_context, authorized_event):
    event = _event(
        authorized_event,
        body={"email": "someone-else@example.com", "value": True},
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 401
    mock_set.assert_not_called()


def test_missing_email_field(mock_context, authorized_event):
    event = _event(authorized_event, body={"value": True})
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_missing_value_field(mock_context, authorized_event):
    event = _event(authorized_event, body={"email": "user@example.com"})
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


def test_rejects_non_bool_value(mock_context, authorized_event):
    event = _event(
        authorized_event,
        body={"email": "user@example.com", "value": "maybe"},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.users_set_likes_public.handler.set_likes_public")
def test_accepts_stringy_bool_true(mock_set, mock_context, authorized_event):
    mock_set.return_value = True
    event = _event(
        authorized_event,
        body={"email": "user@example.com", "value": "true"},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 200
    mock_set.assert_called_once_with("user@example.com", True)


@patch("lambdas.users_set_likes_public.handler.set_likes_public")
def test_accepts_stringy_bool_false(mock_set, mock_context, authorized_event):
    mock_set.return_value = False
    event = _event(
        authorized_event,
        body={"email": "user@example.com", "value": "FALSE"},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 200
    mock_set.assert_called_once_with("user@example.com", False)
