"""
Tests for shares_comments_delete lambda.

Covers:
- delete by comment author -> 200
- delete by share author -> 200
- delete by stranger -> 401 (AuthorizationError)
- missing share -> 404
- missing comment -> 404
- missing required fields -> 400
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_comments_delete.handler import handler


def _event(api_gateway_event, body):
    return {
        **api_gateway_event,
        "httpMethod": "DELETE",
        "path": "/shares/comments",
        "body": json.dumps(body),
    }


def _share():
    return {
        "shareId": "share-1",
        "email": "alice@example.com",  # share author
    }


def _comment(author="bob@example.com"):
    return {
        "shareId": "share-1",
        "commentId": "c-1",
        "createdAtId": "2026-04-23T12:00:00+00:00#c-1",
        "email": author,
        "body": "fire",
        "createdAt": "2026-04-23T12:00:00+00:00",
    }


@patch("lambdas.shares_comments_delete.handler.delete_comment")
@patch("lambdas.shares_comments_delete.handler.get_comment")
@patch("lambdas.shares_comments_delete.handler.get_share")
def test_comment_author_can_delete(
    mock_get_share, mock_get_comment, mock_delete, mock_context, api_gateway_event
):
    mock_get_share.return_value = _share()
    mock_get_comment.return_value = _comment()

    body = {
        "email": "bob@example.com",  # comment author
        "shareId": "share-1",
        "commentId": "c-1",
    }
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["deleted"] is True
    assert payload["commentId"] == "c-1"
    mock_delete.assert_called_once_with("share-1", "2026-04-23T12:00:00+00:00#c-1")


@patch("lambdas.shares_comments_delete.handler.delete_comment")
@patch("lambdas.shares_comments_delete.handler.get_comment")
@patch("lambdas.shares_comments_delete.handler.get_share")
def test_share_author_can_delete(
    mock_get_share, mock_get_comment, mock_delete, mock_context, api_gateway_event
):
    mock_get_share.return_value = _share()
    mock_get_comment.return_value = _comment()

    body = {
        "email": "alice@example.com",  # share author
        "shareId": "share-1",
        "commentId": "c-1",
    }
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 200
    mock_delete.assert_called_once()


@patch("lambdas.shares_comments_delete.handler.delete_comment")
@patch("lambdas.shares_comments_delete.handler.get_comment")
@patch("lambdas.shares_comments_delete.handler.get_share")
def test_third_party_forbidden(
    mock_get_share, mock_get_comment, mock_delete, mock_context, api_gateway_event
):
    mock_get_share.return_value = _share()
    mock_get_comment.return_value = _comment()

    body = {
        "email": "stranger@example.com",
        "shareId": "share-1",
        "commentId": "c-1",
    }
    response = handler(_event(api_gateway_event, body), mock_context)
    # AuthorizationError -> 401 in this codebase.
    assert response["statusCode"] == 401
    mock_delete.assert_not_called()


@patch("lambdas.shares_comments_delete.handler.delete_comment")
@patch("lambdas.shares_comments_delete.handler.get_comment")
@patch("lambdas.shares_comments_delete.handler.get_share")
def test_missing_share(
    mock_get_share, mock_get_comment, mock_delete, mock_context, api_gateway_event
):
    mock_get_share.return_value = None
    body = {"email": "bob@example.com", "shareId": "missing", "commentId": "c-1"}
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 404
    mock_get_comment.assert_not_called()
    mock_delete.assert_not_called()


@patch("lambdas.shares_comments_delete.handler.delete_comment")
@patch("lambdas.shares_comments_delete.handler.get_comment")
@patch("lambdas.shares_comments_delete.handler.get_share")
def test_missing_comment(
    mock_get_share, mock_get_comment, mock_delete, mock_context, api_gateway_event
):
    mock_get_share.return_value = _share()
    mock_get_comment.return_value = None
    body = {"email": "bob@example.com", "shareId": "share-1", "commentId": "missing"}
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 404
    mock_delete.assert_not_called()


@patch("lambdas.shares_comments_delete.handler.delete_comment")
@patch("lambdas.shares_comments_delete.handler.get_comment")
@patch("lambdas.shares_comments_delete.handler.get_share")
def test_missing_required_fields(
    mock_get_share, mock_get_comment, mock_delete, mock_context, api_gateway_event
):
    body = {"email": "bob@example.com"}
    response = handler(_event(api_gateway_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()
    mock_get_comment.assert_not_called()
    mock_delete.assert_not_called()
