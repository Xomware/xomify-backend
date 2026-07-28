"""
Tests for favorites get / list-create / list-history / list-delete handlers.

Handler dependencies (DDB helpers) are patched at the point of import in each
handler module. Caller identity comes from the authorizer context.
"""

import json
from unittest.mock import patch


# ============================================
# favorites_get
# ============================================

@patch("lambdas.favorites_get.handler.get_lists_for_year")
def test_favorites_get_splits_overall_and_custom(mock_get_lists, authorized_event, mock_context):
    from lambdas.favorites_get.handler import handler

    mock_get_lists.return_value = [
        {
            "listId": "overall:2026:songs",
            "category": "songs",
            "genreLabel": "Overall",
            "items": [{"rank": 2, "spotifyId": "s2"}, {"rank": 1, "spotifyId": "s1"}],
        },
        {
            "listId": "custom-1",
            "category": "albums",
            "genreLabel": "Jazz",
            "items": [{"rank": 1, "spotifyId": "a1"}],
        },
    ]

    event = authorized_event(httpMethod="GET", queryStringParameters={"year": "2026"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["year"] == 2026
    # Overall songs sorted by rank ascending.
    assert [i["spotifyId"] for i in body["overall"]["songs"]] == ["s1", "s2"]
    assert body["overall"]["albums"] == []
    assert len(body["lists"]) == 1
    assert body["lists"][0]["listId"] == "custom-1"
    assert body["lists"][0]["genreLabel"] == "Jazz"


def test_favorites_get_missing_year_is_400(authorized_event, mock_context):
    from lambdas.favorites_get.handler import handler

    event = authorized_event(httpMethod="GET", queryStringParameters={})
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["field"] == "year"


def test_favorites_get_non_int_year_is_400(authorized_event, mock_context):
    from lambdas.favorites_get.handler import handler

    event = authorized_event(httpMethod="GET", queryStringParameters={"year": "notayear"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 400


def test_favorites_get_missing_identity_is_401(mock_context, legacy_event):
    from lambdas.favorites_get.handler import handler

    event = legacy_event()
    event["queryStringParameters"] = {"year": "2026"}
    response = handler(event, mock_context)

    assert response["statusCode"] == 401


# ============================================
# favorites_list_create
# ============================================

@patch("lambdas.favorites_list_create.handler.put_list")
def test_list_create_happy_path(mock_put_list, authorized_event, mock_context):
    from lambdas.favorites_list_create.handler import handler

    event = authorized_event(
        httpMethod="POST",
        body=json.dumps({"year": 2026, "category": "albums", "genreLabel": "Jazz"}),
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["year"] == 2026
    assert body["category"] == "albums"
    assert body["genreLabel"] == "Jazz"
    assert body["items"] == []
    assert body["listId"]
    mock_put_list.assert_called_once()


@patch("lambdas.favorites_list_create.handler.put_list")
def test_list_create_bad_category_is_400(mock_put_list, authorized_event, mock_context):
    from lambdas.favorites_list_create.handler import handler

    event = authorized_event(
        httpMethod="POST",
        body=json.dumps({"year": 2026, "category": "playlists", "genreLabel": "x"}),
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_put_list.assert_not_called()


@patch("lambdas.favorites_list_create.handler.put_list")
def test_list_create_missing_field_is_400(mock_put_list, authorized_event, mock_context):
    from lambdas.favorites_list_create.handler import handler

    event = authorized_event(httpMethod="POST", body=json.dumps({"year": 2026}))
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_put_list.assert_not_called()


# ============================================
# favorites_list_history
# ============================================

@patch("lambdas.favorites_list_history.handler.get_history")
def test_list_history_maps_events(mock_get_history, authorized_event, mock_context):
    from lambdas.favorites_list_history.handler import handler

    mock_get_history.return_value = [
        {"ts": "2026-01-01T00:00:00", "spotifyId": "s1", "fromRank": None, "toRank": 1, "sk": "HIST#l1#..#0"},
        {"ts": "2026-01-02T00:00:00", "spotifyId": "s1", "fromRank": 1, "toRank": 2},
    ]

    event = authorized_event(httpMethod="GET", queryStringParameters={"listId": "l1"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["listId"] == "l1"
    assert len(body["events"]) == 2
    # Only the contract fields are exposed (no sk leak).
    assert set(body["events"][0].keys()) == {"ts", "spotifyId", "fromRank", "toRank"}
    assert body["events"][0]["fromRank"] is None


def test_list_history_missing_list_id_is_400(authorized_event, mock_context):
    from lambdas.favorites_list_history.handler import handler

    event = authorized_event(httpMethod="GET", queryStringParameters={})
    response = handler(event, mock_context)

    assert response["statusCode"] == 400


# ============================================
# favorites_list_delete
# ============================================

@patch("lambdas.favorites_list_delete.handler.delete_list")
def test_list_delete_happy_path(mock_delete, authorized_event, mock_context):
    from lambdas.favorites_list_delete.handler import handler

    event = authorized_event(
        httpMethod="DELETE",
        queryStringParameters={"listId": "l1", "year": "2026"},
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {"deleted": True, "listId": "l1"}
    mock_delete.assert_called_once_with("test@example.com", 2026, "l1")


@patch("lambdas.favorites_list_delete.handler.delete_list")
def test_list_delete_missing_year_is_400(mock_delete, authorized_event, mock_context):
    from lambdas.favorites_list_delete.handler import handler

    event = authorized_event(httpMethod="DELETE", queryStringParameters={"listId": "l1"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 400
    mock_delete.assert_not_called()
