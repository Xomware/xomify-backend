"""
Tests for the public_top_items lambda (GET /music/public-top-items).

Public, unauthenticated endpoint serving an allowlisted user's cached
short_term top items in the flattened frontend contract.

Covers:
- Allowlisted user, cache hit -> 200 flattened shape, <=5 each,
  windowLabel/updatedAt present, nowPlaying null, no Spotify call.
- Allowlisted user, cache miss + full success -> live fetch, cache written,
  transformed 200.
- userId NOT on the allowlist (but a real user) -> 404 (no existence leak).
- Unknown userId (resolver returns None) -> 404.
- Missing userId query param -> 400.
- Partial failure on short_term, no cache -> 200 with empty arrays +
  updatedAt: null, cache NOT written.
- Transform unit tests: top-5 slicing, multi-artist join, defensive missing
  album/external_urls, genre dict -> sorted list.

The cache table and users table are mocked — they are provisioned in a
separate infra repo and unavailable locally.
"""

import json
from unittest.mock import patch

import pytest

from lambdas.common.top_items_transform import flatten_public_top_items
from lambdas.public_top_items import handler as public_handler
from lambdas.public_top_items.handler import handler


# Allowlisted userId used across handler tests. We patch the module-level
# allowlist so tests do not depend on the placeholder/real id.
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
    """Build an unauthenticated API Gateway event with optional userId qs."""
    qs = {}
    if not omit and user_id is not None:
        qs["userId"] = user_id
    return {
        "httpMethod": "GET",
        "path": "/music/public-top-items",
        "queryStringParameters": qs or None,
        "headers": {"Content-Type": "application/json"},
        "body": None,
        "isBase64Encoded": False,
    }


@pytest.fixture
def cached_short_term():
    """Range-keyed cache payload with rich short_term Spotify objects."""
    return {
        "tracks": {
            "short_term": [
                {
                    "name": f"Song {i}",
                    "artists": [{"name": f"Artist {i}"}, {"name": f"Feat {i}"}],
                    "album": {"images": [{"url": f"https://art/{i}.jpg"}]},
                    "external_urls": {"spotify": f"https://open.spotify.com/track/{i}"},
                }
                for i in range(8)  # 8 -> must slice to 5
            ],
            "medium_term": [],
            "long_term": [],
        },
        "artists": {
            "short_term": [
                {
                    "name": f"Artist {i}",
                    "images": [{"url": f"https://img/{i}.jpg"}],
                    "external_urls": {"spotify": f"https://open.spotify.com/artist/{i}"},
                }
                for i in range(8)
            ],
            "medium_term": [],
            "long_term": [],
        },
        "genres": {
            "short_term": {"pop": 10, "rock": 8, "indie": 6, "jazz": 4, "edm": 2, "folk": 1},
            "medium_term": {},
            "long_term": {},
        },
        "cachedAt": "2026-06-01T12:00:00+00:00",
    }


# ============================================
# Handler-level tests
# ============================================


@patch("lambdas.public_top_items.handler.set_cached")
@patch("lambdas.public_top_items.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.public_top_items.handler.get_cached_with_meta")
@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_public_user_cache_hit_returns_flattened_shape(
    mock_resolve,
    mock_get_cached,
    mock_fetch,
    mock_set_cached,
    mock_context,
    public_user,
    cached_short_term,
):
    mock_resolve.return_value = public_user
    mock_get_cached.return_value = cached_short_term

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])

    assert len(body["topTracks"]) == 5
    assert len(body["topArtists"]) == 5
    assert len(body["topGenres"]) == 5
    assert body["windowLabel"] == "Last 4 weeks"
    assert body["updatedAt"] == "2026-06-01T12:00:00+00:00"
    assert body["nowPlaying"] is None

    # Flattened track shape with multi-artist join.
    assert body["topTracks"][0]["name"] == "Song 0"
    assert body["topTracks"][0]["artist"] == "Artist 0, Feat 0"
    assert body["topTracks"][0]["albumArt"] == "https://art/0.jpg"
    assert body["topTracks"][0]["url"] == "https://open.spotify.com/track/0"
    assert set(body["topArtists"][0].keys()) == {"name", "image", "url"}
    # Genres sorted desc by count.
    assert body["topGenres"][0] == {"genre": "pop", "count": 10}

    # No Spotify call on a cache hit.
    mock_fetch.assert_not_called()
    mock_set_cached.assert_not_called()


@patch("lambdas.public_top_items.handler.set_cached")
@patch("lambdas.public_top_items.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.public_top_items.handler.get_cached_with_meta")
@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_public_user_cache_miss_full_success_fetches_and_writes_cache(
    mock_resolve,
    mock_get_cached,
    mock_fetch,
    mock_set_cached,
    mock_context,
    public_user,
):
    mock_resolve.return_value = public_user
    mock_get_cached.return_value = None  # cache miss

    live_payload = {
        "tracks": {
            "short_term": [
                {
                    "name": "Live Song",
                    "artists": [{"name": "Live Artist"}],
                    "album": {"images": [{"url": "https://art/live.jpg"}]},
                    "external_urls": {"spotify": "https://open.spotify.com/track/live"},
                }
            ],
            "medium_term": [],
            "long_term": [],
        },
        "artists": {
            "short_term": [
                {
                    "name": "Live Artist",
                    "images": [{"url": "https://img/live.jpg"}],
                    "external_urls": {"spotify": "https://open.spotify.com/artist/live"},
                }
            ],
            "medium_term": [],
            "long_term": [],
        },
        "genres": {"short_term": {"pop": 3}, "medium_term": {}, "long_term": {}},
    }
    mock_fetch.return_value = (live_payload, [])

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["topTracks"][0]["name"] == "Live Song"
    assert body["topTracks"][0]["artist"] == "Live Artist"
    assert body["topGenres"] == [{"genre": "pop", "count": 3}]
    # Live (uncached) payload -> updatedAt null.
    assert body["updatedAt"] is None

    mock_fetch.assert_called_once_with(public_user)
    mock_set_cached.assert_called_once_with("dom@example.com", live_payload)


@patch("lambdas.public_top_items.handler.get_cached_with_meta")
@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_non_public_user_returns_404(
    mock_resolve, mock_get_cached, mock_context
):
    """A real user not on the allowlist -> 404 (no existence leak)."""
    mock_resolve.return_value = {"email": "other@example.com", "userId": "not-public"}

    response = handler(_event("not-public"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    # Cache must never be consulted for a non-public user.
    mock_get_cached.assert_not_called()


@patch("lambdas.public_top_items.handler.get_cached_with_meta")
@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_unknown_user_id_returns_404(
    mock_resolve, mock_get_cached, mock_context
):
    """Resolver returns None -> 404, indistinguishable from non-public."""
    mock_resolve.return_value = None

    response = handler(_event("ghost"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    mock_get_cached.assert_not_called()


@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_missing_user_id_param_returns_400(mock_resolve, mock_context):
    response = handler(_event(omit=True), mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    assert body["error"].get("field") == "userId"
    # Never even attempt resolution without a userId.
    mock_resolve.assert_not_called()


@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_blank_user_id_param_returns_400(mock_resolve, mock_context):
    response = handler(_event("   "), mock_context)

    assert response["statusCode"] == 400
    mock_resolve.assert_not_called()


@patch("lambdas.public_top_items.handler.set_cached")
@patch("lambdas.public_top_items.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.public_top_items.handler.get_cached_with_meta")
@patch("lambdas.public_top_items.handler.get_user_by_user_id")
def test_short_term_failure_no_cache_returns_empty_200(
    mock_resolve,
    mock_get_cached,
    mock_fetch,
    mock_set_cached,
    mock_context,
    public_user,
):
    """Total failure on short_term with no cache -> 200 empty, no 5xx, no write."""
    mock_resolve.return_value = public_user
    mock_get_cached.return_value = None

    failed_payload = {
        "tracks": {"short_term": None, "medium_term": [{"name": "m"}], "long_term": None},
        "artists": {"short_term": None, "medium_term": [], "long_term": None},
        "genres": {"short_term": None, "medium_term": {}, "long_term": None},
    }
    mock_fetch.return_value = (failed_payload, ["short_term"])

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["topTracks"] == []
    assert body["topArtists"] == []
    assert body["topGenres"] == []
    assert body["updatedAt"] is None
    assert body["windowLabel"] == "Last 4 weeks"
    assert body["nowPlaying"] is None

    # Partial failure must NOT write to cache.
    mock_set_cached.assert_not_called()


# ============================================
# Transform unit tests
# ============================================


def test_transform_slices_to_five_and_joins_artists():
    payload = {
        "tracks": {
            "short_term": [
                {
                    "name": f"T{i}",
                    "artists": [{"name": "A"}, {"name": "B"}],
                    "album": {"images": [{"url": "x"}]},
                    "external_urls": {"spotify": "u"},
                }
                for i in range(10)
            ]
        },
        "artists": {"short_term": [{"name": f"AR{i}", "images": [], "external_urls": {}} for i in range(10)]},
        "genres": {"short_term": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}},
    }
    result = flatten_public_top_items(payload, "2026-06-01T00:00:00+00:00")

    assert len(result["topTracks"]) == 5
    assert len(result["topArtists"]) == 5
    assert len(result["topGenres"]) == 5
    assert result["topTracks"][0]["artist"] == "A, B"
    # Genres sorted desc -> top is f:6.
    assert result["topGenres"][0] == {"genre": "f", "count": 6}
    assert result["updatedAt"] == "2026-06-01T00:00:00+00:00"


def test_transform_handles_missing_album_and_external_urls():
    """Conftest-style sparse objects must not blow up."""
    payload = {
        "tracks": {"short_term": [{"name": "Bare", "artists": [{"name": "Solo"}]}]},
        "artists": {"short_term": [{"name": "BareArtist"}]},
        "genres": {"short_term": {}},
    }
    result = flatten_public_top_items(payload, None)

    track = result["topTracks"][0]
    assert track["name"] == "Bare"
    assert track["artist"] == "Solo"
    assert track["albumArt"] is None
    assert track["url"] is None

    artist = result["topArtists"][0]
    assert artist["image"] is None
    assert artist["url"] is None
    assert result["updatedAt"] is None
    assert result["topGenres"] == []


def test_transform_none_payload_returns_empty_contract():
    result = flatten_public_top_items(None, None)
    assert result == {
        "topTracks": [],
        "topArtists": [],
        "topGenres": [],
        "windowLabel": "Last 4 weeks",
        "updatedAt": None,
        "nowPlaying": None,
    }


def test_transform_genre_dict_sorts_desc():
    payload = {"genres": {"short_term": {"low": 1, "high": 100, "mid": 50}}}
    result = flatten_public_top_items(payload, None)
    assert [g["genre"] for g in result["topGenres"]] == ["high", "mid", "low"]
