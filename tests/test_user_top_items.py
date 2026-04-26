"""
Tests for user_top_items lambda.

Covers (epic Track 2 / sub-feature 2a):
- Cache hit short-circuits the Spotify call.
- Cache miss + all-success fetches live, writes the cache, returns full data.
- Cache miss + one-range failure returns a partial payload with
  `meta.failed_ranges` and DOES NOT write the cache.
- Missing caller identity (no JWT context, no fallback) returns structured 401.
- TTL boundary on `cachedAt`:
    - cachedAt today UTC -> hit
    - cachedAt yesterday UTC -> miss
- DDB cache table I/O is mocked (the table is provisioned by 2a-infra in a
  separate repo and is not available locally).
"""

import asyncio
import json
from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lambdas.common import top_items_cache
from lambdas.user_top_items.handler import (
    _empty_top_items_skeleton,
    _fetch_top_items_with_partial_tolerance,
    handler,
)


# ============================================
# Fixtures
# ============================================


@pytest.fixture
def cached_payload():
    return {
        "tracks": {
            "short_term": [{"id": "t1", "name": "Cached Song"}],
            "medium_term": [],
            "long_term": [],
        },
        "artists": {
            "short_term": [{"id": "a1", "name": "Cached Artist"}],
            "medium_term": [],
            "long_term": [],
        },
        "genres": {
            "short_term": {"pop": 5},
            "medium_term": {},
            "long_term": {},
        },
    }


@pytest.fixture
def live_payload():
    """Mirror of what `Spotify.get_top_items_for_api()` returns on success."""
    return {
        "tracks": {
            "short_term": [{"id": "ts", "name": "Live Short Song"}],
            "medium_term": [{"id": "tm", "name": "Live Medium Song"}],
            "long_term": [{"id": "tl", "name": "Live Long Song"}],
        },
        "artists": {
            "short_term": [{"id": "as", "name": "Live Short Artist"}],
            "medium_term": [{"id": "am", "name": "Live Medium Artist"}],
            "long_term": [{"id": "al", "name": "Live Long Artist"}],
        },
        "genres": {
            "short_term": {"pop": 10},
            "medium_term": {"rock": 5},
            "long_term": {"jazz": 3},
        },
    }


# ============================================
# Handler-level tests
# ============================================


@patch("lambdas.user_top_items.handler.set_cached")
@patch("lambdas.user_top_items.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.user_top_items.handler.get_user_table_data")
@patch("lambdas.user_top_items.handler.get_cached")
def test_cache_hit_returns_cached_without_spotify_call(
    mock_get_cached,
    mock_get_user,
    mock_fetch,
    mock_set_cached,
    authorized_event,
    mock_context,
    cached_payload,
):
    mock_get_cached.return_value = cached_payload

    response = handler(authorized_event(), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["tracks"]["short_term"][0]["name"] == "Cached Song"
    assert "meta" not in body  # no failed ranges
    mock_get_user.assert_not_called()
    mock_fetch.assert_not_called()
    mock_set_cached.assert_not_called()


@patch("lambdas.user_top_items.handler.set_cached")
@patch("lambdas.user_top_items.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.user_top_items.handler.get_user_table_data")
@patch("lambdas.user_top_items.handler.get_cached")
def test_cache_miss_full_success_writes_cache_and_returns_full(
    mock_get_cached,
    mock_get_user,
    mock_fetch,
    mock_set_cached,
    authorized_event,
    mock_context,
    sample_user,
    live_payload,
):
    mock_get_cached.return_value = None
    mock_get_user.return_value = sample_user
    mock_fetch.return_value = (live_payload, [])

    response = handler(authorized_event(), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["tracks"]["short_term"][0]["name"] == "Live Short Song"
    assert body["artists"]["medium_term"][0]["name"] == "Live Medium Artist"
    assert body["genres"]["long_term"]["jazz"] == 3
    assert "meta" not in body

    mock_get_user.assert_called_once_with("test@example.com")
    mock_fetch.assert_called_once_with(sample_user)
    mock_set_cached.assert_called_once_with("test@example.com", live_payload)


@patch("lambdas.user_top_items.handler.set_cached")
@patch("lambdas.user_top_items.handler._fetch_top_items_with_partial_tolerance")
@patch("lambdas.user_top_items.handler.get_user_table_data")
@patch("lambdas.user_top_items.handler.get_cached")
def test_cache_miss_partial_failure_returns_meta_and_skips_cache_write(
    mock_get_cached,
    mock_get_user,
    mock_fetch,
    mock_set_cached,
    authorized_event,
    mock_context,
    sample_user,
):
    mock_get_cached.return_value = None
    mock_get_user.return_value = sample_user

    partial_payload = {
        "tracks": {
            "short_term": None,
            "medium_term": [{"id": "tm"}],
            "long_term": [{"id": "tl"}],
        },
        "artists": {
            "short_term": [{"id": "as"}],
            "medium_term": [{"id": "am"}],
            "long_term": [{"id": "al"}],
        },
        "genres": {
            "short_term": {"pop": 1},
            "medium_term": {"rock": 1},
            "long_term": {"jazz": 1},
        },
    }
    mock_fetch.return_value = (partial_payload, ["short_term"])

    response = handler(authorized_event(), mock_context)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["tracks"]["short_term"] is None
    assert body["tracks"]["medium_term"][0]["id"] == "tm"
    assert body["meta"]["failed_ranges"] == ["short_term"]

    # Critical: partial failure must NOT write to cache so a retry can fix it.
    mock_set_cached.assert_not_called()


def test_missing_caller_context_returns_401(api_gateway_event, mock_context):
    """No authorizer context, no email in query/body -> structured 401."""
    response = handler(api_gateway_event, mock_context)

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error"]["status"] == 401
    assert body["error"].get("field") == "email"


# ============================================
# TTL boundary (cache freshness gate, epic Q7)
# ============================================


def _ddb_item_with_cached_at(cached_at_iso: str) -> dict:
    return {
        "email": "test@example.com",
        "tracks": {"short_term": [], "medium_term": [], "long_term": []},
        "artists": {"short_term": [], "medium_term": [], "long_term": []},
        "genres": {"short_term": {}, "medium_term": {}, "long_term": {}},
        "cachedAt": cached_at_iso,
        "ttl": 9999999999,
    }


@patch("lambdas.common.top_items_cache.dynamodb")
def test_get_cached_today_utc_is_hit(mock_dynamo):
    today_iso = datetime.now(timezone.utc).isoformat()
    mock_table = MagicMock()
    mock_table.get_item.return_value = {"Item": _ddb_item_with_cached_at(today_iso)}
    mock_dynamo.Table.return_value = mock_table

    result = top_items_cache.get_cached("test@example.com")

    assert result is not None
    assert "tracks" in result and "artists" in result and "genres" in result


@patch("lambdas.common.top_items_cache.dynamodb")
def test_get_cached_yesterday_utc_is_miss(mock_dynamo):
    """Even though the row exists, cachedAt < today_utc.date() must miss
    so we never serve a stale day to the client (epic Q7)."""
    yesterday_midday = datetime.combine(
        datetime.now(timezone.utc).date() - timedelta(days=1),
        time(hour=12),
        tzinfo=timezone.utc,
    )
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": _ddb_item_with_cached_at(yesterday_midday.isoformat())
    }
    mock_dynamo.Table.return_value = mock_table

    result = top_items_cache.get_cached("test@example.com")

    assert result is None


@patch("lambdas.common.top_items_cache.dynamodb")
def test_get_cached_no_row_is_miss(mock_dynamo):
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    mock_dynamo.Table.return_value = mock_table

    assert top_items_cache.get_cached("test@example.com") is None


@patch("lambdas.common.top_items_cache.dynamodb")
def test_get_cached_missing_cached_at_is_miss(mock_dynamo):
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {
            "email": "test@example.com",
            "tracks": {},
            "artists": {},
            "genres": {},
        }
    }
    mock_dynamo.Table.return_value = mock_table

    assert top_items_cache.get_cached("test@example.com") is None


@patch("lambdas.common.top_items_cache.dynamodb")
def test_set_cached_writes_full_item_with_ttl_and_cached_at(mock_dynamo, live_payload):
    mock_table = MagicMock()
    mock_dynamo.Table.return_value = mock_table

    top_items_cache.set_cached("test@example.com", live_payload)

    mock_table.put_item.assert_called_once()
    written_item = mock_table.put_item.call_args.kwargs["Item"]
    assert written_item["email"] == "test@example.com"
    assert written_item["tracks"] == live_payload["tracks"]
    assert written_item["artists"] == live_payload["artists"]
    assert written_item["genres"] == live_payload["genres"]
    assert isinstance(written_item["cachedAt"], str) and written_item["cachedAt"]
    # TTL is at least the next UTC midnight; sanity check it's in the future.
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    assert written_item["ttl"] > now_epoch


# ============================================
# Per-range partial-tolerance unit tests
# ============================================


def _fake_track_list(term: str, items=None, raise_err: Exception | None = None):
    """Build a stand-in for `TrackList` with the attributes the handler reads."""
    fake = MagicMock()
    fake.term = term
    fake.track_list = items if items is not None else [{"id": f"track-{term}"}]
    if raise_err is None:
        fake.set_top_tracks = AsyncMock(return_value=None)
    else:
        fake.set_top_tracks = AsyncMock(side_effect=raise_err)
    return fake


def _fake_artist_list(
    term: str, items=None, genres=None, raise_err: Exception | None = None
):
    fake = MagicMock()
    fake.term = term
    fake.artist_list = items if items is not None else [{"id": f"artist-{term}"}]
    fake.top_genres = genres if genres is not None else {term: 1}
    if raise_err is None:
        fake.set_top_artists = AsyncMock(return_value=None)
    else:
        fake.set_top_artists = AsyncMock(side_effect=raise_err)
    return fake


def _build_fake_spotify(track_specs: dict, artist_specs: dict) -> MagicMock:
    """track_specs / artist_specs map term -> Exception | None (None = success)."""
    fake = MagicMock()
    fake.aiohttp_initialize_top_items = AsyncMock(return_value=None)
    fake.top_tracks_short = _fake_track_list("short_term", raise_err=track_specs.get("short_term"))
    fake.top_tracks_medium = _fake_track_list("medium_term", raise_err=track_specs.get("medium_term"))
    fake.top_tracks_long = _fake_track_list("long_term", raise_err=track_specs.get("long_term"))
    fake.top_artists_short = _fake_artist_list("short_term", raise_err=artist_specs.get("short_term"))
    fake.top_artists_medium = _fake_artist_list("medium_term", raise_err=artist_specs.get("medium_term"))
    fake.top_artists_long = _fake_artist_list("long_term", raise_err=artist_specs.get("long_term"))
    return fake


@patch("lambdas.user_top_items.handler.aiohttp.ClientSession")
@patch("lambdas.user_top_items.handler.Spotify")
def test_fetch_full_success_returns_no_failed_ranges(mock_spotify_cls, mock_session_cls, sample_user):
    mock_spotify_cls.return_value = _build_fake_spotify({}, {})
    # aiohttp.ClientSession() is used as an async context manager.
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_cls.return_value = mock_session

    payload, failed = asyncio.run(_fetch_top_items_with_partial_tolerance(sample_user))

    assert failed == []
    for term in ("short_term", "medium_term", "long_term"):
        assert payload["tracks"][term] is not None
        assert payload["artists"][term] is not None
        assert payload["genres"][term] is not None


@patch("lambdas.user_top_items.handler.aiohttp.ClientSession")
@patch("lambdas.user_top_items.handler.Spotify")
def test_fetch_one_track_range_failure_records_only_that_range(
    mock_spotify_cls, mock_session_cls, sample_user
):
    mock_spotify_cls.return_value = _build_fake_spotify(
        {"short_term": RuntimeError("Spotify 429")}, {}
    )
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_cls.return_value = mock_session

    payload, failed = asyncio.run(_fetch_top_items_with_partial_tolerance(sample_user))

    assert failed == ["short_term"]
    assert payload["tracks"]["short_term"] is None
    assert payload["tracks"]["medium_term"] is not None
    # Artists for short_term still succeeded -> populated; genres also populated.
    assert payload["artists"]["short_term"] is not None
    assert payload["genres"]["short_term"] is not None


@patch("lambdas.user_top_items.handler.aiohttp.ClientSession")
@patch("lambdas.user_top_items.handler.Spotify")
def test_fetch_artist_failure_nulls_genres_for_that_range(
    mock_spotify_cls, mock_session_cls, sample_user
):
    mock_spotify_cls.return_value = _build_fake_spotify(
        {}, {"medium_term": RuntimeError("Spotify timeout")}
    )
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session_cls.return_value = mock_session

    payload, failed = asyncio.run(_fetch_top_items_with_partial_tolerance(sample_user))

    assert failed == ["medium_term"]
    assert payload["artists"]["medium_term"] is None
    assert payload["genres"]["medium_term"] is None
    assert payload["tracks"]["medium_term"] is not None  # tracks succeeded


# ============================================
# Skeleton sanity
# ============================================


def test_empty_top_items_skeleton_shape():
    skeleton = _empty_top_items_skeleton()
    assert set(skeleton.keys()) == {"tracks", "artists", "genres"}
    for kind in ("tracks", "artists", "genres"):
        assert set(skeleton[kind].keys()) == {"short_term", "medium_term", "long_term"}
        assert all(v is None for v in skeleton[kind].values())
