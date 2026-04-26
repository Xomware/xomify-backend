"""
Tests for the /likes/by-user lambda.

Covers:
- Friend access -> 200 with paginated rows.
- Self access -> bypasses friendship check.
- Non-friend access -> 403/401.
- Privacy gate: friend reading a target with likes_public=false -> 403/401.
- Self can read their own likes regardless of likes_public.
- Pagination params: limit/offset bounds enforced.
- Missing targetEmail -> 400.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.likes_by_user.handler import handler


def _get_event(authorized_event, *, caller="me@example.com", target="friend@example.com", **qs):
    qsp = {"targetEmail": target}
    qsp.update({k: str(v) for k, v in qs.items()})
    return authorized_event(
        email=caller,
        httpMethod="GET",
        path="/likes/by-user",
        queryStringParameters=qsp,
    )


# ---------------------------------------------------------------- Friend success
@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_friend_can_read_paginated_likes(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 5, "likes_updated_at": "ts", "likes_public": True}
    mock_friends.return_value = True
    mock_query.return_value = {
        "tracks": [
            {"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z", "trackName": "S1"},
            {"trackId": "t2", "addedAt": "2025-04-25T00:00:00Z", "trackName": "S2"},
        ],
        "total": 5,
        "hasMore": True,
    }

    event = _get_event(authorized_event, limit=2, offset=0)
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total"] == 5
    assert body["hasMore"] is True
    assert body["likesPublic"] is True
    assert len(body["tracks"]) == 2
    mock_query.assert_called_once_with("friend@example.com", limit=2, offset=0)


# ---------------------------------------------------------------- Self bypass
@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_self_access_bypasses_friendship_check(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 1, "likes_updated_at": "ts", "likes_public": False}
    mock_query.return_value = {"tracks": [], "total": 0, "hasMore": False}

    event = _get_event(authorized_event, caller="me@example.com", target="me@example.com")
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    # Self can see their own likes regardless of public flag.
    assert body["likesPublic"] is False
    # Friendship lookup must be skipped on self-access.
    mock_friends.assert_not_called()


# ---------------------------------------------------------------- Non-friend gate
@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_non_friend_access_rejected(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 5, "likes_updated_at": "ts", "likes_public": True}
    mock_friends.return_value = False

    event = _get_event(authorized_event)
    response = handler(event, mock_context)

    assert response["statusCode"] == 401  # AuthorizationError -> 401
    mock_query.assert_not_called()


# ---------------------------------------------------------------- Privacy gate
@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_friend_blocked_when_target_likes_private(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 5, "likes_updated_at": "ts", "likes_public": False}
    mock_friends.return_value = True

    event = _get_event(authorized_event)
    response = handler(event, mock_context)

    assert response["statusCode"] == 401  # privacy block surfaces as auth error
    mock_query.assert_not_called()


# ---------------------------------------------------------------- Validation
def test_missing_target_email_400(mock_context, authorized_event):
    event = authorized_event(
        httpMethod="GET",
        path="/likes/by-user",
        queryStringParameters={},
    )
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_limit_bounds_enforced(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 1, "likes_updated_at": "ts", "likes_public": True}
    mock_friends.return_value = True

    event = _get_event(authorized_event, limit=0)
    response = handler(event, mock_context)
    assert response["statusCode"] == 400

    event = _get_event(authorized_event, limit=999)
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_offset_must_be_non_negative(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 1, "likes_updated_at": "ts", "likes_public": True}
    mock_friends.return_value = True

    event = _get_event(authorized_event, offset=-1)
    response = handler(event, mock_context)
    assert response["statusCode"] == 400


@patch("lambdas.likes_by_user.handler.query_user_likes")
@patch("lambdas.likes_by_user.handler.are_users_friends")
@patch("lambdas.likes_by_user.handler.get_likes_settings")
def test_paginated_offset_passed_through(
    mock_settings, mock_friends, mock_query, mock_context, authorized_event
):
    mock_settings.return_value = {"likes_count": 4, "likes_updated_at": "ts", "likes_public": True}
    mock_friends.return_value = True
    mock_query.return_value = {
        "tracks": [{"trackId": "t3", "addedAt": "ts"}],
        "total": 4,
        "hasMore": False,
    }

    event = _get_event(authorized_event, limit=1, offset=3)
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    mock_query.assert_called_once_with("friend@example.com", limit=1, offset=3)
