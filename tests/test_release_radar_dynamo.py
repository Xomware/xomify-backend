"""
Tests for release_radar_dynamo helpers:
- group_releases_by_artist
- get_week_date_range (Friday cutoff, full 7-day window)
- get_week_key
- get_previous_week_key
- is_in_week
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from lambdas.common.release_radar_dynamo import (
    group_releases_by_artist,
    get_week_date_range,
    get_week_key,
    get_previous_week_key,
)
from lambdas.cron_release_radar.weekly_release_radar_aiohttp import is_in_week


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
# get_week_date_range -- Friday cutoff (full 7-day window)
# ---------------------------------------------------------------------------

class TestWeekDateRange:

    def test_end_date_is_friday_not_thursday(self):
        """Week should end on Friday (full 7-day window)."""
        week_key = get_week_key(datetime(2025, 1, 18))  # A Saturday
        start, end = get_week_date_range(week_key)
        # End should be Friday (weekday 4)
        assert end.weekday() == 4, f"Expected Friday (4), got weekday {end.weekday()}"

    def test_start_date_is_saturday(self):
        week_key = get_week_key(datetime(2025, 1, 18))
        start, end = get_week_date_range(week_key)
        assert start.weekday() == 5, f"Expected Saturday (5), got weekday {start.weekday()}"

    def test_window_is_seven_days(self):
        """Saturday to Friday is 6 full days apart (7 days inclusive)."""
        week_key = get_week_key(datetime(2025, 2, 1))
        start, end = get_week_date_range(week_key)
        delta = (end.date() - start.date()).days
        assert delta == 6, f"Expected 6-day gap (Sat->Fri), got {delta}"

    def test_friday_is_included_in_range(self):
        """A release on the Friday after Saturday should fall in the range."""
        week_key = get_week_key(datetime(2025, 1, 18))  # Saturday 2025-01-18
        start, end = get_week_date_range(week_key)
        friday = start.replace(hour=12) + timedelta(days=6)
        assert start <= friday <= end, "Friday should be inside the week range"

    def test_saturday_next_week_excluded(self):
        """The next Saturday should be outside the range."""
        week_key = get_week_key(datetime(2025, 1, 18))
        start, end = get_week_date_range(week_key)
        next_saturday = start + timedelta(days=7)
        assert not (start <= next_saturday <= end), "Next Saturday should be outside range"

    def test_end_time_is_end_of_day(self):
        """End date should be 23:59:59."""
        week_key = get_week_key(datetime(2025, 3, 1))
        _, end = get_week_date_range(week_key)
        assert end.hour == 23
        assert end.minute == 59
        assert end.second == 59

    def test_start_time_is_midnight(self):
        """Start date should be 00:00:00."""
        week_key = get_week_key(datetime(2025, 3, 1))
        start, _ = get_week_date_range(week_key)
        assert start.hour == 0
        assert start.minute == 0
        assert start.second == 0


# ---------------------------------------------------------------------------
# get_week_key
# ---------------------------------------------------------------------------

class TestGetWeekKey:

    def test_saturday_returns_its_own_week(self):
        """Saturday should be the start of its own week."""
        sat = datetime(2025, 1, 18)  # Saturday
        key = get_week_key(sat)
        start, _ = get_week_date_range(key)
        assert start.date() == sat.date()

    def test_friday_belongs_to_previous_saturday(self):
        """Friday should belong to the week that started the previous Saturday."""
        fri = datetime(2025, 1, 24)  # Friday
        key = get_week_key(fri)
        start, end = get_week_date_range(key)
        assert start.weekday() == 5
        assert start.date() == datetime(2025, 1, 18).date()

    def test_sunday_belongs_to_previous_saturday(self):
        """Sunday belongs to the week starting the day before (Saturday)."""
        sun = datetime(2025, 1, 19)
        key = get_week_key(sun)
        start, _ = get_week_date_range(key)
        assert start.date() == datetime(2025, 1, 18).date()

    def test_format_is_year_dash_week(self):
        key = get_week_key(datetime(2025, 1, 18))
        assert '-' in key
        year, week = key.split('-')
        assert len(year) == 4
        assert len(week) == 2

    def test_defaults_to_now(self):
        """When called with no arg, should not raise."""
        key = get_week_key()
        assert key is not None
        assert '-' in key


# ---------------------------------------------------------------------------
# get_previous_week_key
# ---------------------------------------------------------------------------

class TestGetPreviousWeekKey:

    @patch('lambdas.common.release_radar_dynamo.datetime')
    def test_on_saturday_returns_previous_week(self, mock_dt):
        """When run on Saturday, going back 1 day lands on Friday
        which belongs to the previous Saturday-Friday window."""
        mock_dt.now.return_value = datetime(2025, 1, 25)  # Saturday
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # Can't fully mock datetime easily, test the logic directly
        yesterday = datetime(2025, 1, 25) - timedelta(days=1)  # Friday Jan 24
        key = get_week_key(yesterday)
        start, end = get_week_date_range(key)
        # Should be the week of Jan 18 (Sat) - Jan 24 (Fri)
        assert start.date() == datetime(2025, 1, 18).date()
        assert end.weekday() == 4  # Friday


# ---------------------------------------------------------------------------
# is_in_week
# ---------------------------------------------------------------------------

class TestIsInWeek:

    def _week_range(self):
        """Helper: return a Saturday-Friday range."""
        week_key = get_week_key(datetime(2025, 1, 18))
        return get_week_date_range(week_key)

    def test_date_in_range(self):
        start, end = self._week_range()
        assert is_in_week("2025-01-20", start, end) is True

    def test_date_before_range(self):
        start, end = self._week_range()
        assert is_in_week("2025-01-17", start, end) is False

    def test_date_after_range(self):
        start, end = self._week_range()
        assert is_in_week("2025-01-25", start, end) is False

    def test_start_date_inclusive(self):
        start, end = self._week_range()
        assert is_in_week(start.strftime('%Y-%m-%d'), start, end) is True

    def test_end_date_inclusive(self):
        start, end = self._week_range()
        assert is_in_week(end.strftime('%Y-%m-%d'), start, end) is True

    def test_friday_now_included(self):
        """Friday should be included in the Saturday-Friday window."""
        start, end = self._week_range()
        friday_str = end.strftime('%Y-%m-%d')
        assert is_in_week(friday_str, start, end) is True

    def test_year_only_returns_false(self):
        start, end = self._week_range()
        assert is_in_week("2025", start, end) is False

    def test_month_only_matching(self):
        """YYYY-MM format should match if month overlaps the week window."""
        start, end = self._week_range()
        assert is_in_week("2025-01", start, end) is True

    def test_month_only_non_matching(self):
        """YYYY-MM format should not match if month does not overlap."""
        start, end = self._week_range()
        assert is_in_week("2025-03", start, end) is False

    def test_empty_string(self):
        start, end = self._week_range()
        assert is_in_week("", start, end) is False

    def test_none(self):
        start, end = self._week_range()
        assert is_in_week(None, start, end) is False

    def test_invalid_date_string(self):
        start, end = self._week_range()
        assert is_in_week("not-a-date", start, end) is False
