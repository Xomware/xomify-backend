"""
Tests for release_radar_dynamo helpers:
- group_releases_by_artist
- get_week_date_range (Thursday cutoff)
"""

import pytest
from datetime import datetime
from lambdas.common.release_radar_dynamo import (
    group_releases_by_artist,
    get_week_date_range,
    get_week_key,
)


# ---------------------------------------------------------------------------
# group_releases_by_artist
# ---------------------------------------------------------------------------

def _make_release(artist_id, artist_name, album_name, release_date, album_type="single"):
    return {
        "artistId": artist_id,
        "artistName": artist_name,
        "albumId": f"{artist_id}-{album_name}",
        "albumName": album_name,
        "albumType": album_type,
        "releaseDate": release_date,
        "totalTracks": 1,
    }


class TestGroupReleasesByArtist:

    def test_empty_list_returns_empty(self):
        assert group_releases_by_artist([]) == []

    def test_single_release_single_artist(self):
        releases = [_make_release("a1", "Artist One", "Album A", "2025-01-10")]
        grouped = group_releases_by_artist(releases)
        assert len(grouped) == 1
        assert grouped[0]["artistId"] == "a1"
        assert grouped[0]["artistName"] == "Artist One"
        assert len(grouped[0]["releases"]) == 1

    def test_multiple_releases_same_artist_grouped(self):
        releases = [
            _make_release("a1", "Artist One", "Single B", "2025-01-08"),
            _make_release("a1", "Artist One", "Album A", "2025-01-10", "album"),
        ]
        grouped = group_releases_by_artist(releases)
        assert len(grouped) == 1
        assert grouped[0]["artistId"] == "a1"
        # Inner releases sorted newest first
        assert grouped[0]["releases"][0]["albumName"] == "Album A"
        assert grouped[0]["releases"][1]["albumName"] == "Single B"

    def test_multiple_artists_ordered_by_newest_release(self):
        releases = [
            _make_release("a2", "Artist Two", "Old Single", "2025-01-05"),
            _make_release("a1", "Artist One", "New Album", "2025-01-12", "album"),
            _make_release("a3", "Artist Three", "Mid Single", "2025-01-09"),
        ]
        grouped = group_releases_by_artist(releases)
        assert len(grouped) == 3
        # Outer list should be newest-first
        assert grouped[0]["artistId"] == "a1"   # 2025-01-12
        assert grouped[1]["artistId"] == "a3"   # 2025-01-09
        assert grouped[2]["artistId"] == "a2"   # 2025-01-05

    def test_inner_releases_sorted_newest_first(self):
        releases = [
            _make_release("a1", "Artist One", "Older", "2025-01-01"),
            _make_release("a1", "Artist One", "Newer", "2025-01-10"),
            _make_release("a1", "Artist One", "Middle", "2025-01-05"),
        ]
        grouped = group_releases_by_artist(releases)
        dates = [r["releaseDate"] for r in grouped[0]["releases"]]
        assert dates == sorted(dates, reverse=True)

    def test_missing_artist_id_grouped_under_unknown(self):
        releases = [
            {"albumName": "Mystery", "releaseDate": "2025-01-01"},
        ]
        grouped = group_releases_by_artist(releases)
        assert len(grouped) == 1
        assert grouped[0]["artistId"] == "unknown"

    def test_deduplication_across_same_artist(self):
        """Two releases from same artist should be in one group, not two."""
        releases = [
            _make_release("a1", "Artist One", "EP1", "2025-01-07"),
            _make_release("a1", "Artist One", "EP2", "2025-01-03"),
        ]
        grouped = group_releases_by_artist(releases)
        assert len(grouped) == 1
        assert len(grouped[0]["releases"]) == 2


# ---------------------------------------------------------------------------
# get_week_date_range — Thursday cutoff
# ---------------------------------------------------------------------------

class TestWeekDateRange:

    def test_end_date_is_thursday_not_friday(self):
        """Week should end on Thursday, not Friday."""
        week_key = get_week_key(datetime(2025, 1, 18))  # A Saturday
        start, end = get_week_date_range(week_key)
        # End should be Thursday (weekday 3)
        assert end.weekday() == 3, f"Expected Thursday (3), got weekday {end.weekday()}"

    def test_start_date_is_saturday(self):
        week_key = get_week_key(datetime(2025, 1, 18))
        start, end = get_week_date_range(week_key)
        assert start.weekday() == 5, f"Expected Saturday (5), got weekday {start.weekday()}"

    def test_window_is_six_days(self):
        """Saturday to Thursday is 5 full days apart (6 days inclusive)."""
        week_key = get_week_key(datetime(2025, 2, 1))
        start, end = get_week_date_range(week_key)
        delta = (end.date() - start.date()).days
        assert delta == 5, f"Expected 5-day gap (Sat→Thu), got {delta}"

    def test_friday_is_excluded_from_range(self):
        """A release on the Friday after Saturday should not fall in the range."""
        week_key = get_week_key(datetime(2025, 1, 18))  # Saturday 2025-01-18
        start, end = get_week_date_range(week_key)
        friday = start.replace(hour=12) + __import__('datetime').timedelta(days=6)
        assert not (start <= friday <= end), "Friday should be outside the week range"
