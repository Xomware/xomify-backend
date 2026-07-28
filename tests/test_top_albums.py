"""
Tests for the derived top-albums helper (lambdas.common.top_albums).

Covers:
- Grouping tracks by album id and counting frequency.
- Ranking by trackCount desc, ties broken by first-seen order.
- Defensive handling of tracks missing `album` / `id` (conftest-style tracks).
- Shape of the per-range return.
"""

from lambdas.common.top_albums import derive_albums_by_range


def _track(track_id: str, album_id: str, album_name: str, artist: str = "A", image: str = "img") -> dict:
    return {
        "id": track_id,
        "name": f"song-{track_id}",
        "artists": [{"name": artist}],
        "album": {
            "id": album_id,
            "name": album_name,
            "images": [{"url": image}],
        },
    }


def test_groups_and_counts_by_album():
    tracks = {
        "short_term": [
            _track("t1", "alb1", "Album One"),
            _track("t2", "alb1", "Album One"),
            _track("t3", "alb2", "Album Two"),
        ],
        "medium_term": [],
        "long_term": [],
    }

    result = derive_albums_by_range(tracks)
    short = result["short_term"]

    assert len(short) == 2
    # alb1 has 2 tracks -> ranked first.
    assert short[0]["spotifyId"] == "alb1"
    assert short[0]["trackCount"] == 2
    assert short[0]["name"] == "Album One"
    assert short[0]["artist"] == "A"
    assert short[0]["imageUrl"] == "img"
    assert short[1]["spotifyId"] == "alb2"
    assert short[1]["trackCount"] == 1


def test_tie_broken_by_first_seen_order():
    tracks = {
        "short_term": [
            _track("t1", "albB", "B"),
            _track("t2", "albA", "A"),
        ],
        "medium_term": [],
        "long_term": [],
    }

    short = derive_albums_by_range(tracks)["short_term"]
    # Both have trackCount 1; albB seen first -> ranked first.
    assert [a["spotifyId"] for a in short] == ["albB", "albA"]


def test_tracks_without_album_are_skipped():
    tracks = {
        "short_term": [
            {"id": "t1", "name": "no album", "artists": [{"name": "X"}]},  # no album key
            {"id": "t2", "album": {"name": "no id"}},  # album without id
            _track("t3", "alb1", "Album One"),
        ],
        "medium_term": [],
        "long_term": [],
    }

    short = derive_albums_by_range(tracks)["short_term"]
    assert len(short) == 1
    assert short[0]["spotifyId"] == "alb1"


def test_returns_all_ranges_even_when_empty():
    result = derive_albums_by_range({})
    assert set(result.keys()) == {"short_term", "medium_term", "long_term"}
    assert all(result[r] == [] for r in result)


def test_missing_images_yields_empty_image_url():
    tracks = {
        "short_term": [{"id": "t1", "artists": [], "album": {"id": "a1", "name": "A"}}],
        "medium_term": [],
        "long_term": [],
    }
    short = derive_albums_by_range(tracks)["short_term"]
    assert short[0]["imageUrl"] == ""
    assert short[0]["artist"] == ""
