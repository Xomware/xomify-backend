"""
Flatten transform for the public wrapped endpoint.

Collapses a list of stored `MonthlyWrap` items (see
`dynamo_helpers.save_monthly_wrap`) — each carrying BARE Spotify IDs — plus the
already-hydrated track/artist objects into the flat `WrappedArchive` shape the
xomware.com `/music` hub expects. Kept separate from the handler so it is
unit-testable in isolation and carries no AWS/Spotify dependencies.

Hydration itself (IDs -> full objects) happens in the handler via Spotify's
batch endpoints; this module only maps the resulting objects + genre counts into
the frontend contract, reusing `top_items_transform` for the track/artist
mapping (the hydrated objects share the `/me/top/*` shape).

Target frontend contract (pinned — do not drift, newest month first)::

    {
      "months": [{
        "monthKey":   "2026-05",
        "label":      "May 2026",
        "topTracks":  [{ "name", "artist", "albumArt", "url" }],
        "topArtists": [{ "name", "image", "url" }],
        "topGenres":  [{ "genre", "count" }],
        "playlistUrl": "https://open.spotify.com/playlist/{id}" | null
      }],
      "updatedAt": "<iso>" | null
    }
"""

from datetime import datetime
from typing import Any, Optional

from lambdas.common.top_items_transform import (
    _flatten_artist,
    _flatten_track,
    _flatten_genres,
)

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def month_label(month_key: Optional[str]) -> str:
    """
    Human month label from a `YYYY-MM` key (e.g. "2026-05" -> "May 2026").

    Falls back to the raw key if it is missing or malformed, so a bad row never
    blows up the response.
    """
    if not month_key:
        return ""
    try:
        parsed = datetime.strptime(month_key, "%Y-%m")
    except (ValueError, TypeError):
        return month_key
    return f"{_MONTH_NAMES[parsed.month - 1]} {parsed.year}"


def playlist_url(playlist_id: Optional[str]) -> Optional[str]:
    """Build the open.spotify.com playlist URL, or None when no playlist."""
    if not playlist_id:
        return None
    return f"https://open.spotify.com/playlist/{playlist_id}"


def flatten_wrapped_month(
    month_key: Optional[str],
    tracks: Optional[list],
    artists: Optional[list],
    genres: Optional[dict],
    playlist_id: Optional[str],
) -> dict[str, Any]:
    """
    Build one flattened month entry from hydrated objects + genre counts.

    Args:
        month_key: `YYYY-MM` key for the month.
        tracks: Hydrated Spotify track objects (already sliced to top 5).
        artists: Hydrated Spotify artist objects (already sliced to top 5).
        genres: `{genre: count}` map (sorted + sliced by `_flatten_genres`).
        playlist_id: Spotify playlist id, or None.

    Returns:
        One `months[]` entry in the `WrappedArchive` contract.
    """
    return {
        "monthKey": month_key,
        "label": month_label(month_key),
        "topTracks": [_flatten_track(t) for t in (tracks or []) if isinstance(t, dict)],
        "topArtists": [_flatten_artist(a) for a in (artists or []) if isinstance(a, dict)],
        "topGenres": _flatten_genres(genres or {}),
        "playlistUrl": playlist_url(playlist_id),
    }


def flatten_public_wrapped(
    months: Optional[list[dict]],
    updated_at: Optional[str],
) -> dict[str, Any]:
    """
    Assemble the full `WrappedArchive` contract from pre-built month entries.

    Args:
        months: Already-flattened month entries (newest first), or None/empty.
        updated_at: ISO timestamp for the archive (e.g. the newest month's
            createdAt), or None.

    Returns:
        The flat `WrappedArchive` dict.
    """
    return {
        "months": months or [],
        "updatedAt": updated_at,
    }
