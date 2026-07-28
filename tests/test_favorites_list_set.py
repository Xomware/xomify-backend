"""
Tests for favorites_list_set — the rank-history append behavior is a
first-class requirement, so these assert the exact HIST events produced for
new / moved / removed / unchanged items, plus overall auto-create and the 404
path for unknown custom lists.
"""

import json
from unittest.mock import patch


def _set_event(authorized_event, year, list_id, items):
    return authorized_event(
        httpMethod="PUT",
        body=json.dumps({"year": year, "listId": list_id, "items": items}),
    )


def _item(rank, spotify_id):
    return {"rank": rank, "spotifyId": spotify_id, "name": f"n{spotify_id}", "artist": "a", "imageUrl": ""}


@patch("lambdas.favorites_list_set.handler.append_history_events")
@patch("lambdas.favorites_list_set.handler.put_list")
@patch("lambdas.favorites_list_set.handler.get_list")
def test_list_set_appends_events_for_new_moved_removed(
    mock_get_list, mock_put_list, mock_append, authorized_event, mock_context
):
    from lambdas.favorites_list_set.handler import handler

    # Existing: s1@1, s2@2, s3@3
    mock_get_list.return_value = {
        "listId": "l1",
        "category": "songs",
        "genreLabel": "Pop",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "items": [_item(1, "s1"), _item(2, "s2"), _item(3, "s3")],
    }

    # New: s1@1 (unchanged), s2@3 (moved), s4@2 (new); s3 removed.
    new_items = [_item(1, "s1"), _item(3, "s2"), _item(2, "s4")]
    response = handler(_set_event(authorized_event, 2026, "l1", new_items), mock_context)

    assert response["statusCode"] == 200

    mock_append.assert_called_once()
    call_email, call_list_id, events = mock_append.call_args.args
    assert call_email == "test@example.com"
    assert call_list_id == "l1"

    by_id = {e["spotifyId"]: e for e in events}
    # s1 unchanged -> no event
    assert "s1" not in by_id
    # s2 moved 2 -> 3
    assert by_id["s2"] == {"spotifyId": "s2", "fromRank": 2, "toRank": 3}
    # s4 new -> fromRank None
    assert by_id["s4"] == {"spotifyId": "s4", "fromRank": None, "toRank": 2}
    # s3 removed -> toRank None
    assert by_id["s3"] == {"spotifyId": "s3", "fromRank": 3, "toRank": None}

    # createdAt preserved on rewrite.
    written = mock_put_list.call_args.kwargs
    assert written["created_at"] == "2026-01-01T00:00:00+00:00"


@patch("lambdas.favorites_list_set.handler.append_history_events")
@patch("lambdas.favorites_list_set.handler.put_list")
@patch("lambdas.favorites_list_set.handler.get_list")
def test_list_set_no_changes_appends_nothing(
    mock_get_list, mock_put_list, mock_append, authorized_event, mock_context
):
    from lambdas.favorites_list_set.handler import handler

    mock_get_list.return_value = {
        "listId": "l1", "category": "songs", "genreLabel": "Pop",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "items": [_item(1, "s1"), _item(2, "s2")],
    }

    response = handler(
        _set_event(authorized_event, 2026, "l1", [_item(1, "s1"), _item(2, "s2")]),
        mock_context,
    )

    assert response["statusCode"] == 200
    mock_append.assert_not_called()
    mock_put_list.assert_called_once()


@patch("lambdas.favorites_list_set.handler.append_history_events")
@patch("lambdas.favorites_list_set.handler.put_list")
@patch("lambdas.favorites_list_set.handler.get_list")
def test_list_set_overall_auto_creates_when_missing(
    mock_get_list, mock_put_list, mock_append, authorized_event, mock_context
):
    from lambdas.favorites_list_set.handler import handler

    mock_get_list.return_value = None  # missing

    response = handler(
        _set_event(authorized_event, 2026, "overall:2026:albums", [_item(1, "a1")]),
        mock_context,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["category"] == "albums"
    assert body["genreLabel"] == "Overall"
    assert body["listId"] == "overall:2026:albums"

    # New item -> one "new" event.
    _, _, events = mock_append.call_args.args
    assert events == [{"spotifyId": "a1", "fromRank": None, "toRank": 1}]

    written = mock_put_list.call_args.kwargs
    assert written["category"] == "albums"
    assert written["created_at"] is None


@patch("lambdas.favorites_list_set.handler.append_history_events")
@patch("lambdas.favorites_list_set.handler.put_list")
@patch("lambdas.favorites_list_set.handler.get_list")
def test_list_set_unknown_custom_list_is_404(
    mock_get_list, mock_put_list, mock_append, authorized_event, mock_context
):
    from lambdas.favorites_list_set.handler import handler

    mock_get_list.return_value = None

    response = handler(
        _set_event(authorized_event, 2026, "custom-unknown", [_item(1, "s1")]),
        mock_context,
    )

    assert response["statusCode"] == 404
    mock_put_list.assert_not_called()
    mock_append.assert_not_called()


@patch("lambdas.favorites_list_set.handler.get_list")
def test_list_set_missing_fields_is_400(mock_get_list, authorized_event, mock_context):
    from lambdas.favorites_list_set.handler import handler

    event = authorized_event(httpMethod="PUT", body=json.dumps({"year": 2026}))
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_get_list.assert_not_called()


def test_list_set_missing_identity_is_401(mock_context, legacy_event):
    from lambdas.favorites_list_set.handler import handler

    event = legacy_event()
    event["httpMethod"] = "PUT"
    event["body"] = json.dumps({"year": 2026, "listId": "l1", "items": []})
    response = handler(event, mock_context)

    assert response["statusCode"] == 401
