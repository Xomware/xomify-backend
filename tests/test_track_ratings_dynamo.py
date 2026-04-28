"""
Regression tests for track_ratings_dynamo helpers.

Bugs caught here:
  1. `get_single_track_rating_for_user` previously read `response["Items"]`
     from `get_item` (which returns a singular `Item` key, or no key on miss).
     That raised KeyError on every call -> /ratings/track 500'd, the iOS
     detail page rendered "no rating" after a successful save, and ratings
     looked like they didn't persist.
  2. `upsert_track_rating` previously had a ConditionExpression that returned
     {} when re-rating the same value. Callers depending on the response
     payload (e.g. a freshly persisted row to echo back) saw an empty dict.
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock

from lambdas.common.track_ratings_dynamo import (
    get_single_track_rating_for_user,
    upsert_track_rating,
)


@patch('lambdas.common.track_ratings_dynamo.dynamodb')
def test_get_single_track_rating_returns_item_when_present(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "email": "a@b.com",
            "trackId": "t1",
            "rating": Decimal("4.5"),
        }
    }
    mock_ddb.Table.return_value = table

    result = get_single_track_rating_for_user("a@b.com", "t1")

    assert result["trackId"] == "t1"
    assert result["rating"] == Decimal("4.5")


@patch('lambdas.common.track_ratings_dynamo.dynamodb')
def test_get_single_track_rating_returns_empty_dict_on_miss(mock_ddb):
    """get_item returns {} (no 'Item' key) when the row doesn't exist."""
    table = MagicMock()
    table.get_item.return_value = {}
    mock_ddb.Table.return_value = table

    result = get_single_track_rating_for_user("a@b.com", "missing")

    assert result == {}


@patch('lambdas.common.track_ratings_dynamo.dynamodb')
def test_upsert_track_rating_returns_persisted_row(mock_ddb):
    """First write returns the persisted row from ALL_NEW."""
    table = MagicMock()
    table.update_item.return_value = {
        "Attributes": {
            "email": "a@b.com",
            "trackId": "t1",
            "rating": Decimal("4.0"),
        }
    }
    mock_ddb.Table.return_value = table

    result = upsert_track_rating(
        "a@b.com", "t1", 4.0, "Song", "Artist", "art.jpg"
    )

    assert result["rating"] == Decimal("4.0")
    kwargs = table.update_item.call_args.kwargs
    # Critical: no ConditionExpression -- writing the same value twice
    # must still return the canonical row to the caller.
    assert "ConditionExpression" not in kwargs


@patch('lambdas.common.track_ratings_dynamo.dynamodb')
def test_upsert_track_rating_re_rate_same_value_still_returns_row(mock_ddb):
    """Re-rating the same value must not return {}; UI relies on the row."""
    persisted = {
        "email": "a@b.com",
        "trackId": "t1",
        "rating": Decimal("4.0"),
    }
    table = MagicMock()
    table.update_item.return_value = {"Attributes": persisted}
    mock_ddb.Table.return_value = table

    result = upsert_track_rating(
        "a@b.com", "t1", 4.0, "Song", "Artist", "art.jpg"
    )

    assert result == persisted
