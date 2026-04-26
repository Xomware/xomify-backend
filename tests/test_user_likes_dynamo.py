"""
Tests for lambdas/common/user_likes_dynamo helpers.

Covers:
- ``set_user_likes_count`` writes count + timestamp.
- ``get_likes_settings`` returns sane defaults (count=0, public=True) for
  legacy/missing rows and handles the explicit-false case.
- ``upsert_user_likes`` no-ops when the table env var is unset, otherwise
  writes capped-and-cleaned items via batch_writer.
- ``query_user_likes`` returns ``{tracks,total,hasMore}`` with offset/limit
  pagination and degrades to empty when the table env var is unset.
- ``set_likes_public`` flips the toggle.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lambdas.common import user_likes_dynamo
from lambdas.common.errors import DynamoDBError


# ---------------------------------------------------------------- Counters
@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_set_user_likes_count_writes_count_and_timestamp(mock_ddb):
    table = MagicMock()
    mock_ddb.Table.return_value = table

    ts = user_likes_dynamo.set_user_likes_count(
        "user@example.com", 42, updated_at="2025-01-01T00:00:00+00:00"
    )

    assert ts == "2025-01-01T00:00:00+00:00"
    table.update_item.assert_called_once()
    call = table.update_item.call_args.kwargs
    assert call["Key"] == {"email": "user@example.com"}
    assert ":c" in call["ExpressionAttributeValues"]
    assert call["ExpressionAttributeValues"][":c"] == 42
    assert call["ExpressionAttributeValues"][":ts"] == "2025-01-01T00:00:00+00:00"


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_set_user_likes_count_generates_timestamp_when_omitted(mock_ddb):
    table = MagicMock()
    mock_ddb.Table.return_value = table

    ts = user_likes_dynamo.set_user_likes_count("user@example.com", 5)

    assert isinstance(ts, str) and len(ts) > 0
    table.update_item.assert_called_once()


def test_set_user_likes_count_requires_email():
    with pytest.raises(DynamoDBError):
        user_likes_dynamo.set_user_likes_count("", 1)


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_set_user_likes_count_wraps_ddb_failures(mock_ddb):
    table = MagicMock()
    table.update_item.side_effect = RuntimeError("boom")
    mock_ddb.Table.return_value = table

    with pytest.raises(DynamoDBError):
        user_likes_dynamo.set_user_likes_count("user@example.com", 1)


# ---------------------------------------------------------------- Settings read
@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_get_likes_settings_defaults_for_missing_user(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {}
    mock_ddb.Table.return_value = table

    settings = user_likes_dynamo.get_likes_settings("missing@example.com")

    assert settings == {
        "likes_count": 0,
        "likes_updated_at": None,
        "likes_public": True,
    }


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_get_likes_settings_reads_existing_row(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {
            "email": "user@example.com",
            "likes_count": 17,
            "likes_updated_at": "2025-04-26T00:00:00+00:00",
            "likes_public": False,
        }
    }
    mock_ddb.Table.return_value = table

    settings = user_likes_dynamo.get_likes_settings("user@example.com")

    assert settings["likes_count"] == 17
    assert settings["likes_updated_at"] == "2025-04-26T00:00:00+00:00"
    assert settings["likes_public"] is False


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_get_likes_settings_coerces_stringy_bool(mock_ddb):
    table = MagicMock()
    table.get_item.return_value = {
        "Item": {"email": "u@example.com", "likes_public": "false"}
    }
    mock_ddb.Table.return_value = table

    settings = user_likes_dynamo.get_likes_settings("u@example.com")
    assert settings["likes_public"] is False


# ---------------------------------------------------------------- Upsert items
def test_upsert_user_likes_noop_when_table_unset(monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "")
    written = user_likes_dynamo.upsert_user_likes(
        "u@example.com",
        [{"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z"}],
    )
    assert written == 0


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_upsert_user_likes_writes_each_track(mock_ddb, monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    table = MagicMock()
    batch = MagicMock()
    table.batch_writer.return_value.__enter__.return_value = batch
    mock_ddb.Table.return_value = table

    tracks = [
        {
            "trackId": "t1",
            "addedAt": "2025-04-26T00:00:00Z",
            "name": "Song One",
            "artist": "Artist A",
            "albumArt": "https://img/a.jpg",
        },
        {
            "trackId": "t2",
            "addedAt": "2025-04-25T00:00:00Z",
            "trackName": "Song Two",
            "artistName": "Artist B",
        },
    ]
    written = user_likes_dynamo.upsert_user_likes("u@example.com", tracks)

    assert written == 2
    assert batch.put_item.call_count == 2
    items = [call.kwargs["Item"] for call in batch.put_item.call_args_list]
    assert items[0]["email"] == "u@example.com"
    assert items[0]["trackId"] == "t1"
    assert items[0]["trackName"] == "Song One"
    assert items[0]["artistName"] == "Artist A"
    assert items[0]["albumArt"] == "https://img/a.jpg"
    # composite sort key
    assert items[0]["addedAtTrackId"] == "2025-04-26T00:00:00Z#t1"
    assert items[1]["trackName"] == "Song Two"
    assert items[1]["artistName"] == "Artist B"
    assert "albumArt" not in items[1]


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_upsert_user_likes_caps_payload(mock_ddb, monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    monkeypatch.setattr(user_likes_dynamo, "MAX_LIKES_PAGE", 3)
    table = MagicMock()
    batch = MagicMock()
    table.batch_writer.return_value.__enter__.return_value = batch
    mock_ddb.Table.return_value = table

    tracks = [
        {"trackId": f"t{i}", "addedAt": f"2025-04-26T00:00:0{i}Z"} for i in range(10)
    ]
    written = user_likes_dynamo.upsert_user_likes("u@example.com", tracks)

    assert written == 3


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_upsert_user_likes_skips_rows_without_required_keys(mock_ddb, monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    table = MagicMock()
    batch = MagicMock()
    table.batch_writer.return_value.__enter__.return_value = batch
    mock_ddb.Table.return_value = table

    tracks = [
        {"trackId": "t1", "addedAt": "2025-04-26T00:00:00Z"},
        {"trackId": None, "addedAt": "2025-04-26T00:00:01Z"},
        {"trackId": "t3", "addedAt": None},
    ]
    written = user_likes_dynamo.upsert_user_likes("u@example.com", tracks)

    assert written == 1


def test_upsert_user_likes_requires_email(monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    with pytest.raises(DynamoDBError):
        user_likes_dynamo.upsert_user_likes("", [{"trackId": "t1", "addedAt": "ts"}])


# ---------------------------------------------------------------- Query items
def test_query_user_likes_noop_when_table_unset(monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "")
    result = user_likes_dynamo.query_user_likes("u@example.com")
    assert result == {"tracks": [], "total": 0, "hasMore": False}


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_query_user_likes_returns_paginated_slice(mock_ddb, monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    table = MagicMock()
    items = [
        {
            "email": "u@example.com",
            "addedAtTrackId": f"2025-04-2{i}T00:00:00Z#t{i}",
            "trackId": f"t{i}",
            "addedAt": f"2025-04-2{i}T00:00:00Z",
            "trackName": f"Song {i}",
            "artistName": f"Artist {i}",
        }
        for i in range(5)
    ]
    table.query.return_value = {"Items": items}
    mock_ddb.Table.return_value = table

    result = user_likes_dynamo.query_user_likes("u@example.com", limit=2, offset=1)

    assert result["total"] == 5
    assert result["hasMore"] is True
    assert len(result["tracks"]) == 2
    assert result["tracks"][0]["trackId"] == "t1"
    # Internal composite sort key must not leak.
    for row in result["tracks"]:
        assert "addedAtTrackId" not in row


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_query_user_likes_last_page_has_no_more(mock_ddb, monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    table = MagicMock()
    items = [
        {
            "email": "u@example.com",
            "addedAtTrackId": f"2025-04-2{i}#t{i}",
            "trackId": f"t{i}",
            "addedAt": f"2025-04-2{i}",
        }
        for i in range(3)
    ]
    table.query.return_value = {"Items": items}
    mock_ddb.Table.return_value = table

    result = user_likes_dynamo.query_user_likes("u@example.com", limit=10, offset=0)

    assert result["total"] == 3
    assert result["hasMore"] is False
    assert len(result["tracks"]) == 3


@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_query_user_likes_caps_at_max_page(mock_ddb, monkeypatch):
    monkeypatch.setattr(user_likes_dynamo, "USER_LIKES_TABLE_NAME", "test-table")
    monkeypatch.setattr(user_likes_dynamo, "MAX_LIKES_PAGE", 3)
    table = MagicMock()
    items = [
        {
            "email": "u@example.com",
            "addedAtTrackId": f"x#t{i}",
            "trackId": f"t{i}",
            "addedAt": "x",
        }
        for i in range(10)
    ]
    table.query.return_value = {"Items": items}
    mock_ddb.Table.return_value = table

    result = user_likes_dynamo.query_user_likes("u@example.com", limit=10, offset=0)

    assert result["total"] == 3


def test_query_user_likes_requires_email():
    with pytest.raises(DynamoDBError):
        user_likes_dynamo.query_user_likes("")


# ---------------------------------------------------------------- Settings write
@patch("lambdas.common.user_likes_dynamo.dynamodb")
def test_set_likes_public_persists_value(mock_ddb):
    table = MagicMock()
    mock_ddb.Table.return_value = table

    persisted = user_likes_dynamo.set_likes_public("u@example.com", False)

    assert persisted is False
    table.update_item.assert_called_once()
    call = table.update_item.call_args.kwargs
    assert call["ExpressionAttributeValues"][":v"] is False


def test_set_likes_public_requires_email():
    with pytest.raises(DynamoDBError):
        user_likes_dynamo.set_likes_public("", True)
