"""
Tests for shares_comments_create lambda.

Covers:
- happy path (creates row, hydrates author profile)
- empty / over-length body -> 400
- missing required fields -> 400
- missing share -> 404
- group-only share, viewer not a member -> 404
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_comments_create.handler import handler


def _event(api_gateway_event, body):
    return {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/shares/comments",
        "body": json.dumps(body),
    }


def _share(share_id="share-1", author="alice@example.com", public=True, group_ids=None):
    return {
        "shareId": share_id,
        "email": author,
        "trackId": "spotify:track:1",
        "trackName": "Song",
        "public": public,
        "groupIds": group_ids or [],
    }


# -------------------------------------------------------------------- Happy path
@patch("lambdas.shares_comments_create.handler.batch_get_users")
@patch("lambdas.shares_comments_create.handler.create_comment")
@patch("lambdas.shares_comments_create.handler.get_share")
def test_happy_path(
    mock_get_share, mock_create, mock_users, mock_context, api_gateway_event
):
    mock_get_share.return_value = _share()
    mock_create.return_value = {
        "shareId": "share-1",
        "commentId": "c-1",
        "email": "bob@example.com",
        "body": "fire track",
        "createdAt": "2026-04-23T12:00:00+00:00",
        "createdAtId": "2026-04-23T12:00:00+00:00#c-1",
    }
    mock_users.return_value = {
        "bob@example.com": {
            "email": "bob@example.com",
            "displayName": "Bob",
            "avatar": "b.jpg",
        }
    }

    body = {"email": "bob@example.com", "shareId": "share-1", "body": "fire track"}
    response = handler(_event(api_gateway_event, body), mock_context)

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["commentId"] == "c-1"
    assert payload["body"] == "fire track"
    assert payload["displayName"] == "Bob"
    assert payload["avatar"] == "b.jpg"
    assert payload["email"] == "bob@example.com"
    mock_create.assert_called_once_with(
        share_id="share-1", email="bob@example.com", body="fire track"
    )


# ------------------------------------------------------------------ Validation
@patch("lambdas.shares_comments_create.handler.create_comment")
@patch("lambdas.shares_comments_create.handler.get_share")
def test_missing_required_fields(
    mock_get_share, mock_create, mock_context, api_gateway_event
):
    body = {"email": "bob@example.com", "shareId": "share-1"}
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()
    mock_create.assert_not_called()


@patch("lambdas.shares_comments_create.handler.create_comment")
@patch("lambdas.shares_comments_create.handler.get_share")
def test_empty_body_rejected(
    mock_get_share, mock_create, mock_context, api_gateway_event
):
    body = {"email": "bob@example.com", "shareId": "share-1", "body": "   "}
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_create.assert_not_called()


@patch("lambdas.shares_comments_create.handler.create_comment")
@patch("lambdas.shares_comments_create.handler.get_share")
def test_body_too_long_rejected(
    mock_get_share, mock_create, mock_context, api_gateway_event
):
    body = {
        "email": "bob@example.com",
        "shareId": "share-1",
        "body": "a" * 501,
    }
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_create.assert_not_called()


# ------------------------------------------------------------------ 404 cases
@patch("lambdas.shares_comments_create.handler.create_comment")
@patch("lambdas.shares_comments_create.handler.get_share")
def test_share_not_found(
    mock_get_share, mock_create, mock_context, api_gateway_event
):
    mock_get_share.return_value = None
    body = {"email": "bob@example.com", "shareId": "missing", "body": "hi"}
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 404
    mock_create.assert_not_called()


@patch("lambdas.common.share_visibility.is_member_of_group")
@patch("lambdas.shares_comments_create.handler.create_comment")
@patch("lambdas.shares_comments_create.handler.get_share")
def test_group_only_share_blocks_non_member(
    mock_get_share, mock_create, mock_member, mock_context, api_gateway_event
):
    mock_get_share.return_value = _share(public=False, group_ids=["g1"])
    mock_member.return_value = False

    body = {
        "email": "stranger@example.com",
        "shareId": "share-1",
        "body": "hi",
    }
    response = handler(_event(api_gateway_event, body), mock_context)
    # Existence is hidden -> 404, not 403.
    assert response["statusCode"] == 404
    mock_create.assert_not_called()
