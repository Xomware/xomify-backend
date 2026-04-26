"""
Tests for shares_reactions_list lambda.

Covers:
- happy path: counts + viewerReactions
- missing share -> 404
- missing required fields -> 400
- group-only share, non-member -> 404
- missing caller identity -> 401
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_reactions_list.handler import handler


def _event(authorized_event, params, email="viewer@example.com"):
    return authorized_event(
        email=email,
        httpMethod="GET",
        path="/shares/reactions",
        queryStringParameters=params,
    )


def _share(public=True, group_ids=None):
    return {
        "shareId": "share-1",
        "email": "alice@example.com",
        "public": public,
        "groupIds": group_ids or [],
    }


@patch("lambdas.shares_reactions_list.handler.build_reaction_summary")
@patch("lambdas.shares_reactions_list.handler.get_share")
def test_happy_path(
    mock_get_share, mock_summary, mock_context, authorized_event
):
    mock_get_share.return_value = _share()
    mock_summary.return_value = {
        "counts": {"fire": 3, "heart": 1},
        "viewerReactions": ["fire"],
    }
    response = handler(
        _event(authorized_event, {"shareId": "share-1"}),
        mock_context,
    )
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["counts"] == {"fire": 3, "heart": 1}
    assert payload["viewerReactions"] == ["fire"]
    mock_summary.assert_called_once_with("share-1", "viewer@example.com")


@patch("lambdas.shares_reactions_list.handler.get_share")
def test_missing_required_fields(mock_get_share, mock_context, authorized_event):
    response = handler(
        _event(authorized_event, {}),
        mock_context,
    )
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


@patch("lambdas.shares_reactions_list.handler.get_share")
def test_share_not_found(mock_get_share, mock_context, authorized_event):
    mock_get_share.return_value = None
    response = handler(
        _event(authorized_event, {"shareId": "missing"}),
        mock_context,
    )
    assert response["statusCode"] == 404


@patch("lambdas.common.share_visibility.is_member_of_group")
@patch("lambdas.shares_reactions_list.handler.build_reaction_summary")
@patch("lambdas.shares_reactions_list.handler.get_share")
def test_group_only_blocks_non_member(
    mock_get_share, mock_summary, mock_member, mock_context, authorized_event
):
    mock_get_share.return_value = _share(public=False, group_ids=["g1"])
    mock_member.return_value = False
    response = handler(
        _event(authorized_event, {"shareId": "share-1"}, email="stranger@example.com"),
        mock_context,
    )
    assert response["statusCode"] == 404
    mock_summary.assert_not_called()


# ------------------------------------------------------------------ Auth
@patch("lambdas.shares_reactions_list.handler.get_share")
def test_missing_caller_identity_returns_401(
    mock_get_share, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/shares/reactions",
        "queryStringParameters": {"shareId": "share-1"},
    }
    response = handler(event, mock_context)
    assert response["statusCode"] == 401
    mock_get_share.assert_not_called()
