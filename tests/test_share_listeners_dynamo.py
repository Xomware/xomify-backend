"""
Tests for share_listeners_dynamo helpers.

Coverage:
- mark_listened uses if_not_exists for listenedAt + source (idempotent).
- mark_listened rejects unknown source values up-front (ValueError).
- mark_listened_bulk caps at 25 and loops UpdateItem (one call per id).
- list_listeners_for_share returns the Items list from the DDB query.
- count_listeners returns len(items).
- has_listened distinguishes hit (Item present) from miss (no Item key).
"""

from unittest.mock import patch, MagicMock

import pytest

from lambdas.common.share_listeners_dynamo import (
    count_listeners,
    has_listened,
    list_listeners_for_share,
    mark_listened,
    mark_listened_bulk,
)


# ---------------------------------------------------------------- mark_listened
@patch('lambdas.common.share_listeners_dynamo.dynamodb')
def test_mark_listened_uses_if_not_exists_for_listenedAt_and_source(mock_ddb):
    """First mark must persist listenedAt and source via if_not_exists."""
    table = MagicMock()
    table.update_item.return_value = {
        "Attributes": {
            "shareId": "s1",
            "email": "u@example.com",
            "listenedAt": "2026-04-22T12:00:00+00:00",
            "source": "queue",
        }
    }
    mock_ddb.Table.return_value = table

    result = mark_listened("s1", "u@example.com", source="queue")

    assert result["listenedAt"] == "2026-04-22T12:00:00+00:00"
    assert result["source"] == "queue"
    kwargs = table.update_item.call_args.kwargs
    expr = kwargs["UpdateExpression"]
    # Both listenedAt and source must use if_not_exists so the FIRST listen
    # timestamp / source survive subsequent writes (idempotency contract).
    assert "if_not_exists(#listenedAt" in expr
    assert "if_not_exists(#source" in expr
    assert kwargs["Key"] == {"shareId": "s1", "email": "u@example.com"}


@patch('lambdas.common.share_listeners_dynamo.dynamodb')
def test_mark_listened_idempotent_second_call_does_not_overwrite(mock_ddb):
    """Re-calling mark_listened keeps the FIRST listenedAt (DDB semantics)."""
    table = MagicMock()
    # Simulate the persisted row returning the original timestamp on a re-mark.
    table.update_item.return_value = {
        "Attributes": {
            "shareId": "s1",
            "email": "u@example.com",
            "listenedAt": "2026-04-22T12:00:00+00:00",  # original
            "source": "queue",
            "updatedAt": "2026-04-23T10:00:00+00:00",  # new
        }
    }
    mock_ddb.Table.return_value = table

    result = mark_listened("s1", "u@example.com", source="play")

    # listenedAt + source must still reflect the FIRST write.
    assert result["listenedAt"] == "2026-04-22T12:00:00+00:00"
    assert result["source"] == "queue"


def test_mark_listened_rejects_unknown_source():
    with pytest.raises(ValueError):
        mark_listened("s1", "u@example.com", source="nope")


# --------------------------------------------------------- mark_listened_bulk
@patch('lambdas.common.share_listeners_dynamo.mark_listened')
def test_mark_listened_bulk_loops_update_item(mock_mark):
    mock_mark.return_value = {}

    written = mark_listened_bulk(["s1", "s2", "s3"], "u@example.com", source="queue")

    assert written == 3
    assert mock_mark.call_count == 3
    # Each call uses the same email + source.
    for call in mock_mark.call_args_list:
        assert call.args[1] == "u@example.com"
        assert call.kwargs["source"] == "queue"


def test_mark_listened_bulk_caps_at_25():
    too_many = [f"s{i}" for i in range(26)]
    with pytest.raises(ValueError):
        mark_listened_bulk(too_many, "u@example.com", source="queue")


def test_mark_listened_bulk_empty_returns_zero():
    assert mark_listened_bulk([], "u@example.com", source="queue") == 0


@patch('lambdas.common.share_listeners_dynamo.mark_listened')
def test_mark_listened_bulk_continues_past_individual_failure(mock_mark):
    """A DynamoDBError on a single id must not abort the whole batch."""
    from lambdas.common.errors import DynamoDBError

    def _side(share_id, email, source="queue"):
        if share_id == "s2":
            raise DynamoDBError(message="boom", function="mark_listened")
        return {}

    mock_mark.side_effect = _side

    written = mark_listened_bulk(["s1", "s2", "s3"], "u@example.com", source="queue")
    # Two of the three writes succeeded; s2 failed and was skipped.
    assert written == 2


# --------------------------------------------------- list_listeners / count
@patch('lambdas.common.share_listeners_dynamo.dynamodb')
def test_list_listeners_for_share_returns_items(mock_ddb):
    table = MagicMock()
    table.query.return_value = {
        "Items": [
            {"shareId": "s1", "email": "a@x.com", "listenedAt": "2026-04-22T12:00:00+00:00"},
            {"shareId": "s1", "email": "b@x.com", "listenedAt": "2026-04-22T12:01:00+00:00"},
        ]
    }
    mock_ddb.Table.return_value = table

    result = list_listeners_for_share("s1")

    assert len(result) == 2
    assert {row["email"] for row in result} == {"a@x.com", "b@x.com"}


@patch('lambdas.common.share_listeners_dynamo.list_listeners_for_share')
def test_count_listeners_is_len_of_listeners(mock_list):
    mock_list.return_value = [{"email": "a@x.com"}, {"email": "b@x.com"}]

    assert count_listeners("s1") == 2


# ----------------------------------------------------------------- has_listened
@patch('lambdas.common.share_listeners_dynamo.dynamodb')
def test_has_listened_true_when_item_present(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"shareId": "s1", "email": "a@x.com"},
    }
    mock_ddb.Table.return_value = table

    assert has_listened("s1", "a@x.com") is True


@patch('lambdas.common.share_listeners_dynamo.dynamodb')
def test_has_listened_false_when_no_item_key(mock_ddb):
    """get_item returns {} (no 'Item' key) on miss."""
    table = MagicMock()
    table.get_item.return_value = {}
    mock_ddb.Table.return_value = table

    assert has_listened("s1", "a@x.com") is False


# ----------------------------------------------------------- error wrapping
@patch('lambdas.common.share_listeners_dynamo.dynamodb')
def test_mark_listened_wraps_boto_error_in_dynamodberror(mock_ddb):
    from lambdas.common.errors import DynamoDBError

    table = MagicMock()
    table.update_item.side_effect = RuntimeError("ddb down")
    mock_ddb.Table.return_value = table

    with pytest.raises(DynamoDBError):
        mark_listened("s1", "u@example.com", source="queue")
