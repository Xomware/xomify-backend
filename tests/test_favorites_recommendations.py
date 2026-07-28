"""
Tests for favorites_recommendations.

Scoring aggregates (len - idx) per range with max-dedup, drops items already in
the target list, sorts score-desc, caps at 20.
"""

import json
from unittest.mock import patch


def _track(track_id, name="n", album_id="alb", image="img"):
    return {
        "id": track_id,
        "name": name,
        "artists": [{"name": "Artist"}],
        "album": {"id": album_id, "name": "Album", "images": [{"url": image}]},
    }


def _artist(artist_id, name="n"):
    return {"id": artist_id, "name": name, "images": [{"url": "img"}]}


@patch("lambdas.favorites_recommendations.handler.get_list")
@patch("lambdas.favorites_recommendations.handler.get_cached")
def test_recommendations_songs_scored_and_excluded(
    mock_get_cached, mock_get_list, authorized_event, mock_context
):
    from lambdas.favorites_recommendations.handler import handler

    mock_get_cached.return_value = {
        "tracks": {
            "short_term": [_track("t1"), _track("t2"), _track("t3")],
            "medium_term": [_track("t2")],  # boosts t2 via extra range
            "long_term": [],
        },
        "artists": {"short_term": [], "medium_term": [], "long_term": []},
        "genres": {},
    }
    # t1 already in the target list -> excluded.
    mock_get_list.return_value = {"items": [{"spotifyId": "t1", "rank": 1}]}

    event = authorized_event(
        httpMethod="GET",
        queryStringParameters={"category": "songs", "listId": "l1", "year": "2026"},
    )
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["category"] == "songs"
    assert body["listId"] == "l1"

    ids = [r["spotifyId"] for r in body["recommendations"]]
    assert "t1" not in ids  # excluded (in list)
    # t2 appears in short_term (idx1 -> 3-1=2) and medium_term (idx0 -> 1) -> max 2.
    # t3 short_term idx2 -> 3-2=1. So t2 outranks t3.
    assert ids == ["t2", "t3"]
    t2 = body["recommendations"][0]
    assert t2["score"] == 2
    assert set(t2.keys()) == {"spotifyId", "name", "artist", "imageUrl", "score"}


@patch("lambdas.favorites_recommendations.handler.get_cached")
def test_recommendations_albums_derived(mock_get_cached, authorized_event, mock_context):
    from lambdas.favorites_recommendations.handler import handler

    mock_get_cached.return_value = {
        "tracks": {
            "short_term": [_track("t1", album_id="albA"), _track("t2", album_id="albA")],
            "medium_term": [],
            "long_term": [],
        },
        "artists": {},
        "genres": {},
    }

    event = authorized_event(httpMethod="GET", queryStringParameters={"category": "albums"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["listId"] is None  # no listId provided
    ids = [r["spotifyId"] for r in body["recommendations"]]
    assert ids == ["albA"]


@patch("lambdas.favorites_recommendations.handler.get_cached")
def test_recommendations_artists(mock_get_cached, authorized_event, mock_context):
    from lambdas.favorites_recommendations.handler import handler

    mock_get_cached.return_value = {
        "tracks": {},
        "artists": {
            "short_term": [_artist("ar1"), _artist("ar2")],
            "medium_term": [],
            "long_term": [],
        },
        "genres": {},
    }

    event = authorized_event(httpMethod="GET", queryStringParameters={"category": "artists"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert [r["spotifyId"] for r in body["recommendations"]] == ["ar1", "ar2"]


def test_recommendations_invalid_category_is_400(authorized_event, mock_context):
    from lambdas.favorites_recommendations.handler import handler

    event = authorized_event(httpMethod="GET", queryStringParameters={"category": "playlists"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 400


def test_recommendations_missing_identity_is_401(mock_context, legacy_event):
    from lambdas.favorites_recommendations.handler import handler

    event = legacy_event()
    event["queryStringParameters"] = {"category": "songs"}
    response = handler(event, mock_context)

    assert response["statusCode"] == 401


@patch("lambdas.favorites_recommendations.handler.set_cached")
@patch("lambdas.favorites_recommendations.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.favorites_recommendations.handler.get_user_table_data")
@patch("lambdas.favorites_recommendations.handler.get_cached")
def test_recommendations_cache_miss_fetches_and_caches(
    mock_get_cached, mock_get_user, mock_fetch, mock_set_cached,
    authorized_event, mock_context, sample_user,
):
    from lambdas.favorites_recommendations.handler import handler

    mock_get_cached.return_value = None
    mock_get_user.return_value = sample_user
    payload = {
        "tracks": {"short_term": [_track("t1")], "medium_term": [], "long_term": []},
        "artists": {}, "genres": {},
    }
    mock_fetch.return_value = (payload, [])

    event = authorized_event(httpMethod="GET", queryStringParameters={"category": "songs"})
    response = handler(event, mock_context)

    assert response["statusCode"] == 200
    mock_get_user.assert_called_once_with("test@example.com")
    mock_set_cached.assert_called_once_with("test@example.com", payload)
