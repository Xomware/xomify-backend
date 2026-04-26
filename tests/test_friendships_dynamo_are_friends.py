"""
Tests for the are_users_friends helper added to friendships_dynamo.

The helper backs friend-visibility gates (e.g. /likes/by-user) and must
stay cheap (single GetItem) and forgiving (returns False for the missing
or non-accepted case rather than throwing).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lambdas.common import friendships_dynamo
from lambdas.common.errors import DynamoDBError


@patch("lambdas.common.friendships_dynamo.dynamodb")
def test_returns_true_for_accepted_friendship(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "email": "a@example.com",
            "friendEmail": "b@example.com",
            "status": "accepted",
        }
    }
    mock_ddb.Table.return_value = table

    assert friendships_dynamo.are_users_friends("a@example.com", "b@example.com") is True
    table.get_item.assert_called_once_with(
        Key={"email": "a@example.com", "friendEmail": "b@example.com"}
    )


@patch("lambdas.common.friendships_dynamo.dynamodb")
def test_returns_false_for_pending_friendship(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "email": "a@example.com",
            "friendEmail": "b@example.com",
            "status": "pending",
        }
    }
    mock_ddb.Table.return_value = table

    assert friendships_dynamo.are_users_friends("a@example.com", "b@example.com") is False


@patch("lambdas.common.friendships_dynamo.dynamodb")
def test_returns_false_for_missing_row(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {}
    mock_ddb.Table.return_value = table

    assert friendships_dynamo.are_users_friends("a@example.com", "b@example.com") is False


def test_same_email_short_circuits_to_false():
    """Self-edge has no friendship row; callers should special-case self-access."""
    assert friendships_dynamo.are_users_friends("a@example.com", "a@example.com") is False


def test_empty_inputs_short_circuit_to_false():
    assert friendships_dynamo.are_users_friends("", "b@example.com") is False
    assert friendships_dynamo.are_users_friends("a@example.com", "") is False


@patch("lambdas.common.friendships_dynamo.dynamodb")
def test_ddb_error_is_wrapped(mock_ddb):
    table = MagicMock()
    table.get_item.side_effect = RuntimeError("DDB throttled")
    mock_ddb.Table.return_value = table

    with pytest.raises(DynamoDBError):
        friendships_dynamo.are_users_friends("a@example.com", "b@example.com")
