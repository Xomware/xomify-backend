"""
Tests for the public_now_playing lambda (GET /music/public-now-playing).

Public, unauthenticated endpoint serving an allowlisted user's CURRENT Spotify
playback (with a recently-played fallback) in the frontend now-playing contract:

    { isPlaying, track: {name,artist,albumArt,url}|null, progressMs, durationMs,
      source: "playing"|"recent"|"none", playedAt: str|null }

Covers:
- Allowlisted user, track playing -> 200 source="playing".
- Not playing + recently-played has item -> 200 source="recent" + playedAt.
- Not playing + recently-played 403 (insufficient scope) -> 200 source="none".
- Not playing + recently-played empty -> 200 source="none".
- Spotify 204 / no playback then no recent -> source="none" 200.
- Non-track item (podcast episode, no album/artists) -> graceful, no 500.
- userId NOT on the allowlist (real user) -> 404 (no existence leak).
- Unknown userId (resolver None) -> 404.
- Missing userId query param -> 400.
- Spotify error (raises) -> source="none" 200, never 5xx.

The users table is mocked and the Spotify client is patched — no network.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from lambdas.common.spotify import SpotifyInsufficientScopeError
from lambdas.public_now_playing import handler as np_handler
from lambdas.public_now_playing.handler import handler


PUBLIC_ID = "public-user-1"


@pytest.fixture(autouse=True)
def _allowlist_public_id():
    """Force a deterministic allowlist for the handler under test."""
    with patch.object(np_handler, "PUBLIC_USER_IDS", frozenset({PUBLIC_ID})):
        yield


@pytest.fixture
def public_user():
    return {
        "email": "dom@example.com",
        "userId": PUBLIC_ID,
        "displayName": "Dom",
        "refreshToken": "refresh-xyz",
    }


def _event(user_id=None, omit=False):
    qs = {}
    if not omit and user_id is not None:
        qs["userId"] = user_id
    return {
        "httpMethod": "GET",
        "path": "/music/public-now-playing",
        "queryStringParameters": qs or None,
        "headers": {"Content-Type": "application/json"},
        "body": None,
        "isBase64Encoded": False,
    }


def _playing_state():
    """A realistic `/me/player` payload with a track playing."""
    return {
        "is_playing": True,
        "progress_ms": 42000,
        "currently_playing_type": "track",
        "item": {
            "name": "Live Song",
            "duration_ms": 210000,
            "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
            "album": {"images": [{"url": "https://art/np.jpg"}]},
            "external_urls": {"spotify": "https://open.spotify.com/track/np"},
        },
    }


def _recently_played(played_at="2026-06-01T12:00:00.000Z"):
    """A realistic `/me/player/recently-played?limit=1` payload."""
    return {
        "items": [
            {
                "played_at": played_at,
                "track": {
                    "name": "Recent Song",
                    "duration_ms": 180000,
                    "artists": [{"name": "Recent Artist"}],
                    "album": {"images": [{"url": "https://art/recent.jpg"}]},
                    "external_urls": {
                        "spotify": "https://open.spotify.com/track/recent"
                    },
                },
            }
        ]
    }


def _patch_spotify(
    playback_return=None,
    playback_side_effect=None,
    recent_return=None,
    recent_side_effect=None,
):
    """
    Patch the Spotify class, mocking both get_playback_state and
    get_recently_played on the instance.
    """
    instance = MagicMock()

    if playback_side_effect is not None:
        instance.get_playback_state.side_effect = playback_side_effect
    else:
        instance.get_playback_state.return_value = playback_return

    if recent_side_effect is not None:
        instance.get_recently_played.side_effect = recent_side_effect
    else:
        instance.get_recently_played.return_value = recent_return

    return patch(
        "lambdas.public_now_playing.handler.Spotify", return_value=instance
    )


# ============================================
# Handler tests
# ============================================


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_playing_track_returns_mapped_shape(mock_resolve, mock_context, public_user):
    mock_resolve.return_value = public_user

    with _patch_spotify(playback_return=_playing_state()) as spotify_cls:
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["isPlaying"] is True
    assert body["source"] == "playing"
    assert body["playedAt"] is None
    assert body["progressMs"] == 42000
    assert body["durationMs"] == 210000
    assert body["track"] == {
        "name": "Live Song",
        "artist": "Artist A, Artist B",
        "albumArt": "https://art/np.jpg",
        "url": "https://open.spotify.com/track/np",
    }
    # Actively playing -> recently-played fallback never invoked.
    spotify_cls.return_value.get_recently_played.assert_not_called()


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_not_playing_falls_back_to_recent(mock_resolve, mock_context, public_user):
    """Nothing playing + recently-played has an item -> source=recent + playedAt."""
    mock_resolve.return_value = public_user

    with _patch_spotify(
        playback_return=None, recent_return=_recently_played()
    ) as spotify_cls:
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["isPlaying"] is False
    assert body["source"] == "recent"
    assert body["playedAt"] == "2026-06-01T12:00:00.000Z"
    assert body["progressMs"] is None
    assert body["durationMs"] is None
    assert body["track"] == {
        "name": "Recent Song",
        "artist": "Recent Artist",
        "albumArt": "https://art/recent.jpg",
        "url": "https://open.spotify.com/track/recent",
    }
    spotify_cls.return_value.get_recently_played.assert_called_once_with(limit=1)


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_recent_403_insufficient_scope_returns_none(
    mock_resolve, mock_context, public_user
):
    """Not playing + recently-played 403 insufficient scope -> source=none, 200."""
    mock_resolve.return_value = public_user

    with _patch_spotify(
        playback_return=None,
        recent_side_effect=SpotifyInsufficientScopeError("403 insufficient scope"),
    ):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {
        "isPlaying": False,
        "track": None,
        "progressMs": None,
        "durationMs": None,
        "source": "none",
        "playedAt": None,
    }


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_recent_empty_returns_none(mock_resolve, mock_context, public_user):
    """Not playing + recently-played empty/no items -> source=none, 200."""
    mock_resolve.return_value = public_user

    with _patch_spotify(playback_return=None, recent_return={"items": []}):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["source"] == "none"
    assert body["track"] is None
    assert body["playedAt"] is None


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_recent_error_returns_none(mock_resolve, mock_context, public_user):
    """Not playing + recently-played raises a generic error -> source=none, 200."""
    mock_resolve.return_value = public_user

    with _patch_spotify(
        playback_return=None,
        recent_side_effect=Exception("Spotify 503 timeout"),
    ):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["source"] == "none"
    assert body["track"] is None


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_204_no_playback_no_recent_returns_none(
    mock_resolve, mock_context, public_user
):
    """Spotify 204 (None) + no recently-played -> source=none 200."""
    mock_resolve.return_value = public_user

    with _patch_spotify(playback_return=None, recent_return=None):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {
        "isPlaying": False,
        "track": None,
        "progressMs": None,
        "durationMs": None,
        "source": "none",
        "playedAt": None,
    }


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_non_track_item_degrades_gracefully(mock_resolve, mock_context, public_user):
    """A podcast episode item (no album/artists) must not 500."""
    mock_resolve.return_value = public_user

    episode_state = {
        "is_playing": True,
        "progress_ms": 5000,
        "currently_playing_type": "episode",
        "item": {
            "name": "Some Podcast Episode",
            "duration_ms": 3_600_000,
            "external_urls": {"spotify": "https://open.spotify.com/episode/abc"},
        },
    }

    with _patch_spotify(playback_return=episode_state):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["isPlaying"] is True
    assert body["source"] == "playing"
    assert body["progressMs"] == 5000
    assert body["durationMs"] == 3_600_000
    # Best-effort name, empty artist join, null albumArt — no crash.
    assert body["track"]["name"] == "Some Podcast Episode"
    assert body["track"]["artist"] == ""
    assert body["track"]["albumArt"] is None
    assert body["track"]["url"] == "https://open.spotify.com/episode/abc"


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_paused_device_falls_back_to_recent(mock_resolve, mock_context, public_user):
    """Active device but is_playing False -> not "playing"; falls back to recent."""
    mock_resolve.return_value = public_user

    with _patch_spotify(
        playback_return={"is_playing": False, "item": None},
        recent_return=_recently_played(),
    ):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["isPlaying"] is False
    assert body["source"] == "recent"
    assert body["track"]["name"] == "Recent Song"
    assert body["durationMs"] is None


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_non_public_user_returns_404(mock_resolve, mock_context):
    mock_resolve.return_value = {"email": "other@example.com", "userId": "not-public"}

    with _patch_spotify(playback_return=_playing_state()) as spotify_cls:
        response = handler(_event("not-public"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    # Never build a Spotify client for a non-public user.
    spotify_cls.assert_not_called()


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_unknown_user_id_returns_404(mock_resolve, mock_context):
    mock_resolve.return_value = None

    with _patch_spotify(playback_return=_playing_state()) as spotify_cls:
        response = handler(_event("ghost"), mock_context)

    assert response["statusCode"] == 404
    body = json.loads(response["body"])
    assert body["error"]["status"] == 404
    spotify_cls.assert_not_called()


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_missing_user_id_param_returns_400(mock_resolve, mock_context):
    response = handler(_event(omit=True), mock_context)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error"]["status"] == 400
    assert body["error"].get("field") == "userId"
    mock_resolve.assert_not_called()


@patch("lambdas.public_now_playing.handler.get_user_by_user_id")
def test_playback_error_returns_none_200(mock_resolve, mock_context, public_user):
    """A playback-state error/timeout must degrade to source=none 200, never 5xx."""
    mock_resolve.return_value = public_user

    with _patch_spotify(playback_side_effect=Exception("Spotify 503 timeout")):
        response = handler(_event(PUBLIC_ID), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body == {
        "isPlaying": False,
        "track": None,
        "progressMs": None,
        "durationMs": None,
        "source": "none",
        "playedAt": None,
    }
