"""
Tests for the public_release_radar lambda (GET /music/public-release-radar).

Public, unauthenticated endpoint serving an allowlisted user's most recent
weekly Release Radar snapshot in the flattened `RadarProfile` contract.

Covers:
- Allowlisted user, stored snapshot -> 200 flattened shape (name/artist/
  albumArt/url/releaseDate/type, windowLabel, updatedAt), type mapping.
- userId NOT on the allowlist (but a real user) -> 404 (no existence leak).
- Unknown userId (resolver returns None) -> 404.
- Missing userId query param -> 400.
- No stored data -> 200 with empty releases + updatedAt: null.
- Read failure -> 200 empty (graceful degradation, no 5xx).
- Transform unit tests: type mapping + defensive field mapping.

The history table and users table are mocked — they are provisioned in a
separate infra repo and unavailable locally.
"""

import json
from unittest.mock import patch

import pytest

from lambdas.common.release_radar_transform import (
    flatten_public_release_radar,
    _map_release_type,
)
from lambdas.public_release_radar import handler as public_handler
from lambdas.public_release_radar.handler import handler


PUBLIC_ID = "public-user-1"


@pytest.fixture(autouse=True)
def _allowlist_public_id():
    """Force a deterministic allowlist for the handler under test."""
    with patch.object(public_handler, "PUBLIC_USER_IDS", frozenset({PUBLIC_ID})):
        yield


# ============================================
# Fixtures
# ============================================


@pytest.fixture
def public_user():
    return {
        "email": "dom@example.com",
        "userId": PUBLIC_ID,
        "displayName": "Dom",
    }


def _event(user_id=None, omit=False):
    qs = {}
    if not omit and user_id is not None:
        qs["userId"] = user_id
    return {
        "httpMethod": "GET",
        "path": "/music/public-release-radar",
        "queryStringParameters": qs or None,
        "headers": {"Content-Type": "application/json"},
        "body": None,
        "isBase64Encoded": False,
    }


@pytest.fixture
def stored_week():
    """A release-radar history item as stored by the weekly cron."""
    return {
        "email": "dom@example.com",
        "weekKey": "2026-22",
        "createdAt": "2026-05-31 08:00:00",
        "releases": [
            {
                "albumName": "Big Album",
                "artistName": "Headliner",
                "albumType": "album",
                "releaseDate": "2026-05-30",
                "imageUrl": "https://art/album.jpg",
                "spotifyUrl": "https://open.spotify.com/album/1",
            },
            {
                "albumName": "Lil Single",
                "artistName": "Newcomer",
                "albumType": "single",
                "releaseDate": "2026-05-29",
                "imageUrl": "https://art/single.jpg",
                "spotifyUrl": "https://open.spotify.com/album/2",
            },
            {
                "albumName": "Old School Comp",
                "artistName": "Various",
                "albumType": "compilation",
                "releaseDate": "2026-05-28",
                "imageUrl": None,
                "spotifyUrl": None,
            },
        ],
    }


# ============================================
# Handler-level tests
# ============================================


@patch("lambdas.public_release_radar.handler.get_user_release_radar_history")
@patch("lambdas.public_release_radar.handler.get_user_by_user_id")
def test_public_user_returns_flattened_radar(
    mock_resolve, mock_history, mock_context, public_user, stored_week
):
    mock_resolve.return_value = public_user
    mock_history.return_value = [stored_week]

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])

    assert body["windowLabel"] == "This week"
    assert body["updatedAt"] == "2026-05-31 08:00:00"
    assert len(body["releases"]) == 3

    first = body["releases"][0]
    assert first["name"] == "Big Album"
    assert first["artist"] == "Headliner"
    assert first["albumArt"] == "https://art/album.jpg"
    assert first["url"] == "https://open.spotify.com/album/1"
    assert first["releaseDate"] == "2026-05-30"
    assert first["type"] == "album"

    assert body["releases"][1]["type"] == "single"
    # compilation collapses to 'single'; missing art/url stay None.
    assert body["releases"][2]["type"] == "single"
    assert body["releases"][2]["albumArt"] is None
    assert body["releases"][2]["url"] is None

    # Read latest week only.
    mock_history.assert_called_once_with("dom@example.com", limit=1)


@patch("lambdas.public_release_radar.handler.get_user_release_radar_history")
@patch("lambdas.public_release_radar.handler.get_user_by_user_id")
def test_non_public_user_returns_404(mock_resolve, mock_history, mock_context):
    mock_resolve.return_value = {"email": "other@example.com", "userId": "not-public"}

    response = handler(_event("not-public"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    mock_history.assert_not_called()


@patch("lambdas.public_release_radar.handler.get_user_release_radar_history")
@patch("lambdas.public_release_radar.handler.get_user_by_user_id")
def test_unknown_user_id_returns_404(mock_resolve, mock_history, mock_context):
    mock_resolve.return_value = None

    response = handler(_event("ghost"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    mock_history.assert_not_called()


@patch("lambdas.public_release_radar.handler.get_user_by_user_id")
def test_missing_user_id_param_returns_400(mock_resolve, mock_context):
    response = handler(_event(omit=True), mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    assert body["error"].get("field") == "userId"
    mock_resolve.assert_not_called()


@patch("lambdas.public_release_radar.handler.get_user_release_radar_history")
@patch("lambdas.public_release_radar.handler.get_user_by_user_id")
def test_no_data_returns_empty_200(
    mock_resolve, mock_history, mock_context, public_user
):
    mock_resolve.return_value = public_user
    mock_history.return_value = []

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["releases"] == []
    assert body["updatedAt"] is None
    assert body["windowLabel"] == "This week"


@patch("lambdas.public_release_radar.handler.get_user_release_radar_history")
@patch("lambdas.public_release_radar.handler.get_user_by_user_id")
def test_read_failure_returns_empty_200(
    mock_resolve, mock_history, mock_context, public_user
):
    """A DDB read error degrades to empty 200 rather than a 5xx."""
    mock_resolve.return_value = public_user
    mock_history.side_effect = RuntimeError("ddb down")

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["releases"] == []
    assert body["updatedAt"] is None


# ============================================
# Transform unit tests
# ============================================


def test_transform_none_item_returns_empty_contract():
    result = flatten_public_release_radar(None)
    assert result == {
        "releases": [],
        "windowLabel": "This week",
        "updatedAt": None,
    }


def test_transform_maps_types_and_defaults():
    assert _map_release_type("album") == "album"
    assert _map_release_type("single") == "single"
    assert _map_release_type("ep") == "ep"
    assert _map_release_type("EP") == "ep"
    assert _map_release_type("compilation") == "single"
    assert _map_release_type(None) == "single"
    assert _map_release_type("") == "single"


def test_transform_handles_snake_case_album_type_and_missing_fields():
    item = {
        "createdAt": "2026-05-31 08:00:00",
        "releases": [
            {"album_type": "single"},  # snake_case fallback, all else missing
        ],
    }
    result = flatten_public_release_radar(item)
    rel = result["releases"][0]
    assert rel["type"] == "single"
    assert rel["name"] is None
    assert rel["artist"] is None
    assert rel["albumArt"] is None
    assert rel["url"] is None
    assert result["updatedAt"] == "2026-05-31 08:00:00"
