"""
Tests for the public_wrapped lambda (GET /music/public-wrapped).

Public, unauthenticated endpoint serving an allowlisted user's monthly Wrapped
archive in the flattened `WrappedArchive` contract. The stored wraps hold BARE
Spotify IDs; the handler hydrates short_term top-5 song/artist IDs to full
objects via Spotify's batch endpoints.

Covers:
- Allowlisted user, multiple stored months -> 200 with hydrated months in
  newest-first order; asserts IDs -> objects mapping, genre sort, playlistUrl,
  label, and that the batch hydration was called with the right IDs.
- userId NOT on the allowlist -> 404 (no existence leak).
- Unknown userId -> 404.
- Missing userId query param -> 400.
- No wraps -> 200 with empty months.
- Read failure -> 200 empty (graceful degradation).
- Transform unit tests: month label, playlist url.

Spotify batch calls are mocked — no network is hit. The history/users tables
are mocked (provisioned in a separate infra repo).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from lambdas.common.wrapped_transform import month_label, playlist_url
from lambdas.public_wrapped import handler as public_handler
from lambdas.public_wrapped.handler import handler


PUBLIC_ID = "public-user-1"


@pytest.fixture(autouse=True)
def _allowlist_public_id():
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
        "refreshToken": "mock-refresh-token",
    }


def _event(user_id=None, omit=False):
    qs = {}
    if not omit and user_id is not None:
        qs["userId"] = user_id
    return {
        "httpMethod": "GET",
        "path": "/music/public-wrapped",
        "queryStringParameters": qs or None,
        "headers": {"Content-Type": "application/json"},
        "body": None,
        "isBase64Encoded": False,
    }


def _wrap(month_key, song_ids, artist_ids, genres, playlist_id, created_at):
    """Build a stored MonthlyWrap item (bare IDs)."""
    return {
        "monthKey": month_key,
        "topSongIds": {"short_term": song_ids, "medium_term": [], "long_term": []},
        "topArtistIds": {"short_term": artist_ids, "medium_term": [], "long_term": []},
        "topGenres": {"short_term": genres, "medium_term": {}, "long_term": {}},
        "playlistId": playlist_id,
        "createdAt": created_at,
    }


@pytest.fixture
def wraps():
    """Two stored months, newest first (as get_user_wrap_history returns)."""
    return [
        _wrap(
            "2026-05",
            song_ids=["s1", "s2"],
            artist_ids=["a1", "a2"],
            genres={"pop": 10, "rock": 5, "jazz": 1},
            playlist_id="pl_may",
            created_at="2026-06-01 09:00:00",
        ),
        _wrap(
            "2026-04",
            song_ids=["s3"],
            artist_ids=["a3"],
            genres={"indie": 7},
            playlist_id=None,
            created_at="2026-05-01 09:00:00",
        ),
    ]


def _track_obj(name, artist, art, url):
    return {
        "name": name,
        "artists": [{"name": artist}],
        "album": {"images": [{"url": art}]},
        "external_urls": {"spotify": url},
    }


def _artist_obj(name, img, url):
    return {
        "name": name,
        "images": [{"url": img}],
        "external_urls": {"spotify": url},
    }


def _fake_spotify_factory():
    """A fake Spotify client whose batch getters return hydrated objects keyed
    off the requested IDs, so we can assert the ID -> object mapping."""
    spotify = MagicMock()

    def get_tracks(ids):
        return [_track_obj(f"Song {i}", f"Artist {i}", f"https://art/{i}.jpg",
                           f"https://open.spotify.com/track/{i}") for i in ids]

    def get_artists(ids):
        return [_artist_obj(f"Artist {i}", f"https://img/{i}.jpg",
                            f"https://open.spotify.com/artist/{i}") for i in ids]

    spotify.get_tracks_by_ids.side_effect = get_tracks
    spotify.get_artists_by_ids.side_effect = get_artists
    return spotify


# ============================================
# Handler-level tests
# ============================================


@patch("lambdas.public_wrapped.handler.Spotify")
@patch("lambdas.public_wrapped.handler.get_user_wrap_history")
@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_public_user_hydrates_and_orders_months(
    mock_resolve, mock_history, mock_spotify_cls, mock_context, public_user, wraps
):
    mock_resolve.return_value = public_user
    mock_history.return_value = wraps
    fake = _fake_spotify_factory()
    mock_spotify_cls.return_value = fake

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])

    # Newest month first, updatedAt from newest wrap.
    assert body["updatedAt"] == "2026-06-01 09:00:00"
    assert [m["monthKey"] for m in body["months"]] == ["2026-05", "2026-04"]

    may = body["months"][0]
    assert may["label"] == "May 2026"
    assert may["playlistUrl"] == "https://open.spotify.com/playlist/pl_may"

    # IDs -> hydrated objects mapping (s1/s2 -> two tracks).
    assert [t["name"] for t in may["topTracks"]] == ["Song s1", "Song s2"]
    assert may["topTracks"][0]["artist"] == "Artist s1"
    assert may["topTracks"][0]["albumArt"] == "https://art/s1.jpg"
    assert may["topTracks"][0]["url"] == "https://open.spotify.com/track/s1"
    assert [a["name"] for a in may["topArtists"]] == ["Artist a1", "Artist a2"]
    assert set(may["topArtists"][0].keys()) == {"name", "image", "url"}
    # Genres sorted desc by count.
    assert may["topGenres"][0] == {"genre": "pop", "count": 10}

    apr = body["months"][1]
    assert apr["label"] == "April 2026"
    assert apr["playlistUrl"] is None
    assert [t["name"] for t in apr["topTracks"]] == ["Song s3"]

    # Hydration called with the short_term IDs of each month.
    fake.get_tracks_by_ids.assert_any_call(["s1", "s2"])
    fake.get_tracks_by_ids.assert_any_call(["s3"])
    fake.get_artists_by_ids.assert_any_call(["a1", "a2"])
    fake.get_artists_by_ids.assert_any_call(["a3"])


@patch("lambdas.public_wrapped.handler.get_user_wrap_history")
@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_non_public_user_returns_404(mock_resolve, mock_history, mock_context):
    mock_resolve.return_value = {"email": "other@example.com", "userId": "not-public"}

    response = handler(_event("not-public"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    mock_history.assert_not_called()


@patch("lambdas.public_wrapped.handler.get_user_wrap_history")
@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_unknown_user_id_returns_404(mock_resolve, mock_history, mock_context):
    mock_resolve.return_value = None

    response = handler(_event("ghost"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    mock_history.assert_not_called()


@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_missing_user_id_param_returns_400(mock_resolve, mock_context):
    response = handler(_event(omit=True), mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    assert body["error"].get("field") == "userId"
    mock_resolve.assert_not_called()


@patch("lambdas.public_wrapped.handler.Spotify")
@patch("lambdas.public_wrapped.handler.get_user_wrap_history")
@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_no_wraps_returns_empty_200(
    mock_resolve, mock_history, mock_spotify_cls, mock_context, public_user
):
    mock_resolve.return_value = public_user
    mock_history.return_value = []

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["months"] == []
    assert body["updatedAt"] is None
    # No Spotify client built when there are no wraps.
    mock_spotify_cls.assert_not_called()


@patch("lambdas.public_wrapped.handler.get_user_wrap_history")
@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_read_failure_returns_empty_200(
    mock_resolve, mock_history, mock_context, public_user
):
    mock_resolve.return_value = public_user
    mock_history.side_effect = RuntimeError("ddb down")

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["months"] == []
    assert body["updatedAt"] is None


@patch("lambdas.public_wrapped.handler.Spotify")
@patch("lambdas.public_wrapped.handler.get_user_wrap_history")
@patch("lambdas.public_wrapped.handler.get_user_by_user_id")
def test_month_hydration_failure_is_skipped(
    mock_resolve, mock_history, mock_spotify_cls, mock_context, public_user, wraps
):
    """A month whose hydration raises is skipped, others still render."""
    mock_resolve.return_value = public_user
    mock_history.return_value = wraps

    fake = MagicMock()
    # First month's track hydration blows up; second month succeeds.
    fake.get_tracks_by_ids.side_effect = [
        RuntimeError("spotify 500"),
        [_track_obj("Song s3", "Artist s3", "art", "url")],
    ]
    fake.get_artists_by_ids.return_value = []
    mock_spotify_cls.return_value = fake

    response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    # Only the surviving April month remains.
    assert [m["monthKey"] for m in body["months"]] == ["2026-04"]


# ============================================
# Transform unit tests
# ============================================


def test_month_label_formats_and_falls_back():
    assert month_label("2026-05") == "May 2026"
    assert month_label("2026-01") == "January 2026"
    assert month_label("2026-12") == "December 2026"
    assert month_label("garbage") == "garbage"
    assert month_label(None) == ""


def test_playlist_url_builds_or_nulls():
    assert playlist_url("abc123") == "https://open.spotify.com/playlist/abc123"
    assert playlist_url(None) is None
    assert playlist_url("") is None
