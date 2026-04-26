"""
Tests for shares_reactions_toggle lambda.

Covers:
- toggle on (no row -> insert -> active=true)
- toggle off (existing row -> delete -> active=false)
- multiple emoji per user (independent toggle paths)
- invalid emoji rejected -> 400
- missing share -> 404
- group-only share, non-member -> 404
- missing caller identity -> 401
"""

from __future__ import annotations

import json
from unittest.mock import patch

from lambdas.shares_reactions_toggle.handler import handler


def _event(authorized_event, body, email="bob@example.com"):
    return authorized_event(
        email=email,
        httpMethod="POST",
        path="/shares/reactions",
        body=json.dumps(body),
    )


def _share(public=True, group_ids=None):
    return {
        "shareId": "share-1",
        "email": "alice@example.com",
        "public": public,
        "groupIds": group_ids or [],
    }


# -------------------------------------------------------------------- Toggle on
@patch("lambdas.shares_reactions_toggle.handler.build_reaction_summary")
@patch("lambdas.shares_reactions_toggle.handler.add_reaction")
@patch("lambdas.shares_reactions_toggle.handler.remove_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_toggle_on_inserts_when_missing(
    mock_get_share, mock_get_reaction, mock_remove, mock_add, mock_summary,
    mock_context, authorized_event,
):
    mock_get_share.return_value = _share()
    mock_get_reaction.return_value = None
    mock_summary.return_value = {
        "counts": {"fire": 1},
        "viewerReactions": ["fire"],
    }

    body = {"shareId": "share-1", "reaction": "fire"}
    response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["active"] is True
    assert payload["reaction"] == "fire"
    assert payload["counts"] == {"fire": 1}
    assert payload["viewerReactions"] == ["fire"]
    mock_add.assert_called_once_with("share-1", "bob@example.com", "fire")
    mock_remove.assert_not_called()


# -------------------------------------------------------------------- Toggle off
@patch("lambdas.shares_reactions_toggle.handler.build_reaction_summary")
@patch("lambdas.shares_reactions_toggle.handler.add_reaction")
@patch("lambdas.shares_reactions_toggle.handler.remove_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_toggle_off_deletes_when_present(
    mock_get_share, mock_get_reaction, mock_remove, mock_add, mock_summary,
    mock_context, authorized_event,
):
    mock_get_share.return_value = _share()
    mock_get_reaction.return_value = {
        "shareId": "share-1",
        "email": "bob@example.com",
        "reaction": "fire",
    }
    mock_summary.return_value = {"counts": {}, "viewerReactions": []}

    body = {"shareId": "share-1", "reaction": "fire"}
    response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["active"] is False
    mock_remove.assert_called_once_with("share-1", "bob@example.com", "fire")
    mock_add.assert_not_called()


# ----------------------------------------------------------- Multi-emoji per user
@patch("lambdas.shares_reactions_toggle.handler.build_reaction_summary")
@patch("lambdas.shares_reactions_toggle.handler.add_reaction")
@patch("lambdas.shares_reactions_toggle.handler.remove_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_user_can_have_multiple_emoji_at_once(
    mock_get_share, mock_get_reaction, mock_remove, mock_add, mock_summary,
    mock_context, authorized_event,
):
    """User has 'fire' set, taps 'heart' -> heart is inserted, fire untouched."""
    mock_get_share.return_value = _share()
    # `get_reaction` is keyed on the specific (user, share, reaction).
    # heart row does not exist yet, so it's a fresh insert.
    mock_get_reaction.return_value = None
    mock_summary.return_value = {
        "counts": {"fire": 1, "heart": 1},
        "viewerReactions": ["fire", "heart"],
    }

    body = {"shareId": "share-1", "reaction": "heart"}
    response = handler(_event(authorized_event, body, email="bob@example.com"), mock_context)
    assert response["statusCode"] == 200
    payload = json.loads(response["body"])
    assert payload["active"] is True
    assert payload["reaction"] == "heart"
    assert set(payload["viewerReactions"]) == {"fire", "heart"}
    mock_add.assert_called_once_with("share-1", "bob@example.com", "heart")
    mock_remove.assert_not_called()


# ------------------------------------------------------------------ Validation
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_invalid_emoji_rejected(mock_get_share, mock_context, authorized_event):
    body = {"shareId": "share-1", "reaction": "skull"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_missing_required_fields(mock_get_share, mock_context, authorized_event):
    body = {"shareId": "share-1"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 400
    mock_get_share.assert_not_called()


# ------------------------------------------------------------------ 404 cases
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_share_not_found(mock_get_share, mock_context, authorized_event):
    mock_get_share.return_value = None
    body = {"shareId": "missing", "reaction": "fire"}
    response = handler(_event(authorized_event, body), mock_context)
    assert response["statusCode"] == 404


@patch("lambdas.common.share_visibility.is_member_of_group")
@patch("lambdas.shares_reactions_toggle.handler.add_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_reaction")
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_group_only_blocks_non_member(
    mock_get_share, mock_get_reaction, mock_add, mock_member,
    mock_context, authorized_event,
):
    mock_get_share.return_value = _share(public=False, group_ids=["g1"])
    mock_member.return_value = False
    body = {"shareId": "share-1", "reaction": "fire"}
    response = handler(
        _event(authorized_event, body, email="stranger@example.com"), mock_context
    )
    assert response["statusCode"] == 404
    mock_get_reaction.assert_not_called()
    mock_add.assert_not_called()


# ------------------------------------------------------------------ Auth
@patch("lambdas.shares_reactions_toggle.handler.get_share")
def test_missing_caller_identity_returns_401(
    mock_get_share, mock_context, api_gateway_event
):
    event = {
        **api_gateway_event,
        "httpMethod": "POST",
        "path": "/shares/reactions",
        "body": json.dumps({"shareId": "share-1", "reaction": "fire"}),
    }
    response = handler(event, mock_context)
    assert response["statusCode"] == 401
    mock_get_share.assert_not_called()
