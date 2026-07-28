"""
Tests for lambdas.common.favorites_dynamo helpers.

DDB is mocked by patching the module-level `dynamodb` resource; query results
are supplied as real dicts so the pagination / `.get("Items")` paths behave.
"""

from unittest.mock import MagicMock, patch

from lambdas.common import favorites_dynamo


def test_list_sk_format():
    assert favorites_dynamo.list_sk(2026, "overall:2026:songs") == "LIST#2026#overall:2026:songs"


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_get_lists_for_year_queries_by_prefix(mock_dynamo):
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": [{"listId": "l1"}]}
    mock_dynamo.Table.return_value = mock_table

    rows = favorites_dynamo.get_lists_for_year("u@e.com", 2026)

    assert rows == [{"listId": "l1"}]
    mock_table.query.assert_called_once()


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_get_list_returns_item(mock_dynamo):
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": {"listId": "l1"}}
    mock_dynamo.Table.return_value = mock_table

    row = favorites_dynamo.get_list("u@e.com", 2026, "l1")

    assert row == {"listId": "l1"}
    mock_table.get_item.assert_called_once_with(Key={"email": "u@e.com", "sk": "LIST#2026#l1"})


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_get_list_miss_returns_none(mock_dynamo):
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_dynamo.Table.return_value = mock_table

    assert favorites_dynamo.get_list("u@e.com", 2026, "l1") is None


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_put_list_writes_full_row(mock_dynamo):
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table

    item = favorites_dynamo.put_list(
        email="u@e.com",
        year=2026,
        list_id="l1",
        category="songs",
        genre_label="Pop",
        items=[{"rank": 1, "spotifyId": "s1"}],
    )

    mock_table.put_item.assert_called_once()
    written = mock_table.put_item.call_args.kwargs["Item"]
    assert written["sk"] == "LIST#2026#l1"
    assert written["email"] == "u@e.com"
    assert written["year"] == 2026
    assert written["category"] == "songs"
    assert written["genreLabel"] == "Pop"
    assert written["items"] == [{"rank": 1, "spotifyId": "s1"}]
    assert "createdAt" in written and "updatedAt" in written
    assert item["sk"] == "LIST#2026#l1"


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_put_list_preserves_created_at(mock_dynamo):
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table

    favorites_dynamo.put_list(
        email="u@e.com", year=2026, list_id="l1", category="songs",
        genre_label=None, items=[], created_at="2026-01-01T00:00:00+00:00",
    )
    written = mock_table.put_item.call_args.kwargs["Item"]
    assert written["createdAt"] == "2026-01-01T00:00:00+00:00"
    assert written["genreLabel"] is None


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_append_history_events_writes_each(mock_dynamo):
    mock_table = MagicMock()
    mock_batch = MagicMock()
    mock_table.batch_writer.return_value.__enter__.return_value = mock_batch
    mock_dynamo.Table.return_value = mock_table

    events = [
        {"spotifyId": "s1", "fromRank": None, "toRank": 1},
        {"spotifyId": "s2", "fromRank": 2, "toRank": None},
    ]
    favorites_dynamo.append_history_events("u@e.com", "l1", events)

    assert mock_batch.put_item.call_count == 2
    first = mock_batch.put_item.call_args_list[0].kwargs["Item"]
    assert first["listId"] == "l1"
    assert first["spotifyId"] == "s1"
    assert first["fromRank"] is None
    assert first["toRank"] == 1
    assert first["sk"].startswith("HIST#l1#")
    assert first["sk"].endswith("#000000")


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_append_history_events_noop_on_empty(mock_dynamo):
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table

    favorites_dynamo.append_history_events("u@e.com", "l1", [])
    mock_table.batch_writer.assert_not_called()


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_get_history_queries_ascending(mock_dynamo):
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": [{"ts": "t1"}]}
    mock_dynamo.Table.return_value = mock_table

    rows = favorites_dynamo.get_history("u@e.com", "l1")

    assert rows == [{"ts": "t1"}]
    kwargs = mock_table.query.call_args.kwargs
    assert kwargs["ScanIndexForward"] is True


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_reminder_marker_roundtrip(mock_dynamo):
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": {"sentAt": "x"}}
    mock_dynamo.Table.return_value = mock_table

    assert favorites_dynamo.get_reminder_marker("u@e.com", 2026) == {"sentAt": "x"}
    mock_table.get_item.assert_called_with(Key={"email": "u@e.com", "sk": "REMINDER#2026"})

    favorites_dynamo.put_reminder_marker("u@e.com", 2026)
    written = mock_table.put_item.call_args.kwargs["Item"]
    assert written["sk"] == "REMINDER#2026"
    assert "sentAt" in written


@patch("lambdas.common.favorites_dynamo.dynamodb")
def test_delete_list(mock_dynamo):
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table

    favorites_dynamo.delete_list("u@e.com", 2026, "l1")
    mock_table.delete_item.assert_called_once_with(
        Key={"email": "u@e.com", "sk": "LIST#2026#l1"}
    )
