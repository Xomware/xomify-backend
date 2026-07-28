"""
Tests for the `range` param on GET /favorites/recommendations.

Recs are now scoped to a single listening window's top-items (default
short_term) instead of blending all ranges.
"""

import json
from unittest.mock import patch


def _track(track_id):
    return {
        "id": track_id,
        "name": "n",
        "artists": [{"name": "Artist"}],
        "album": {"id": "alb", "name": "Album", "images": [{"url": "img"}]},
    }


_TOP = {
    "tracks": {
        "short_term": [_track("s1"), _track("s2")],
        "medium_term": [_track("m1")],
        "long_term": [_track("l1")],
    },
    "artists": {},
    "genres": {},
}


@patch("lambdas.favorites_recommendations.handler.get_cached")
def test_default_range_is_short_term(mock_cached, authorized_event, mock_context):
    from lambdas.favorites_recommendations.handler import handler

    mock_cached.return_value = _TOP
    event = authorized_event(httpMethod="GET", queryStringParameters={"category": "songs"})
    resp = handler(event, mock_context)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["range"] == "short_term"
    ids = {r["spotifyId"] for r in body["recommendations"]}
    assert ids == {"s1", "s2"}  # only short_term items, no m1/l1


@patch("lambdas.favorites_recommendations.handler.get_cached")
def test_long_term_range_scopes_source(mock_cached, authorized_event, mock_context):
    from lambdas.favorites_recommendations.handler import handler

    mock_cached.return_value = _TOP
    event = authorized_event(
        httpMethod="GET",
        queryStringParameters={"category": "songs", "range": "long_term"},
    )
    resp = handler(event, mock_context)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["range"] == "long_term"
    assert [r["spotifyId"] for r in body["recommendations"]] == ["l1"]


def test_invalid_range_is_400(authorized_event, mock_context):
    from lambdas.favorites_recommendations.handler import handler

    event = authorized_event(
        httpMethod="GET",
        queryStringParameters={"category": "songs", "range": "yesterday"},
    )
    resp = handler(event, mock_context)
    assert resp["statusCode"] == 400
