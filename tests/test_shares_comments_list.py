"""
Tests for shares_comments_list lambda.

Covers:
- happy path with profile hydration + nextBefore cursor
- limit clamping / validation
- missing share -> 404
- group-only share, non-member -> 404
- missing caller identity -> 401
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_comments_list.handler import handler


def _event(authorized_event, params, email="viewer@example.com"):
    return authorized_event(
        email=email,
        httpMethod="GET",
        path="/shares/comments",
        queryStringParameters=params,
    )


def _share(public=True, group_ids=None):
    return {
        "shareId": "share-1",
        "email": "alice@example.com",
        "trackId": "spotify:track:1",
        "trackName": "Song",
        "public": public,
        "groupIds": group_ids or [],
    }


# -------------------------------------------------------------------- Happy path
@patch("lambdas.shares_comments_list.handler.batch_get_users")
@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_happy_path_with_profiles_and_cursor(
    mock_get_share, mock_list, mock_users, mock_context, authorized_event
):
    mock_get_share.return_value = _share()
    mock_list.return_value = (
        [
            {
                "shareId": "share-1",
                "createdAtId": "2026-04-23T12:01:00+00:00#c-2",
                "commentId": "c-2",
                "email": "carol@example.com",
                "body": "love this",
                "createdAt": "2026-04-23T12:01:00+00:00",
            },
            {
                "shareId": "share-1",
                "createdAtId": "2026-04-23T12:00:00+00:00#c-1",
                "commentId": "c-1",
                "email": "bob@example.com",
                "body": "fire",
                "createdAt": "2026-04-23T12:00:00+00:00",
            },
        ],
        "2026-04-23T12:00:00+00:00",
    )
    mock_users.return_value = {
        "carol@example.com": {"displayName": "Carol", "avatar": "c.jpg"},
        "bob@example.com":   {"displayName": "Bob",   "avatar": "b.jpg"},
    }

    response = handler(
        _event(authorized_event, {
            "shareId": "share-1",
            "limit": "2",
        }),
        mock_context,
    )
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["nextBefore"] == "2026-04-23T12:00:00+00:00"
    assert len(payload["comments"]) == 2
    # Newest first ordering preserved.
    assert payload["comments"][0]["commentId"] == "c-2"
    assert payload["comments"][0]["displayName"] == "Carol"
    assert payload["comments"][1]["commentId"] == "c-1"
    assert payload["comments"][1]["displayName"] == "Bob"


# --------------------------------------------------------------------
# Empty-thread regression
# --------------------------------------------------------------------
# Bug repro: TestFlight users hit /shares/comments on a freshly-created
# share (zero comments yet) and got a 500. The expected response shape
# for an empty thread is `{"comments": [], "nextBefore": null}`. This
# test pins that contract — if we ever regress on empty-list handling,
# the iOS client breaks open-on-share.
@patch("lambdas.shares_comments_list.handler.batch_get_users")
@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_empty_thread_returns_empty_list_not_500(
    mock_get_share, mock_list, mock_users, mock_context, authorized_event
):
    mock_get_share.return_value = _share()
    mock_list.return_value = ([], None)

    response = handler(
        _event(authorized_event, {"shareId": "share-1"}),
        mock_context,
    )

    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload == {"comments": [], "nextBefore": None}
    # Hydrate should not be invoked when there are no authors to look up.
    mock_users.assert_not_called()


# ------------------------------------------------------------------ Validation
@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_limit_must_be_integer(
    mock_get_share, mock_list, mock_context, authorized_event
):
    response = handler(
        _event(authorized_event, {
            "shareId": "share-1",
            "limit": "abc",
        }),
        mock_context,
    )
    assert response["statusCode"] == 400
    mock_list.assert_not_called()


@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_limit_capped(
    mock_get_share, mock_list, mock_context, authorized_event
):
    response = handler(
        _event(authorized_event, {
            "shareId": "share-1",
            "limit": "9999",
        }),
        mock_context,
    )
    assert response["statusCode"] == 400


@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_missing_required_fields(
    mock_get_share, mock_list, mock_context, authorized_event
):
    response = handler(
        _event(authorized_event, {}),
        mock_context,
    )
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


# ------------------------------------------------------------------ 404 cases
@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_share_not_found(
    mock_get_share, mock_list, mock_context, authorized_event
):
    mock_get_share.return_value = None
    response = handler(
        _event(authorized_event, {"shareId": "missing"}),
        mock_context,
    )
    assert response["statusCode"] == 404
    mock_list.assert_not_called()


@patch("lambdas.common.share_visibility.is_member_of_group")
@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_group_only_blocks_non_member(
    mock_get_share, mock_list, mock_member, mock_context, authorized_event
):
    mock_get_share.return_value = _share(public=False, group_ids=["g1"])
    mock_member.return_value = False
    response = handler(
        _event(authorized_event, {"shareId": "share-1"}, email="stranger@example.com"),
        mock_context,
    )
    assert response["statusCode"] == 404
    mock_list.assert_not_called()


# ------------------------------------------------------------------ Auth
@patch("lambdas.shares_comments_list.handler.list_comments")
@patch("lambdas.shares_comments_list.handler.get_share")
def test_missing_caller_identity_returns_401(
    mock_get_share, mock_list, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/shares/comments",
        "queryStringParameters": {"shareId": "share-1"},
    }
    response = handler(event, mock_context)
    assert response["statusCode"] == 401
    mock_get_share.assert_not_called()
    mock_list.assert_not_called()
