"""
Flatten transform for the public release-radar endpoint.

Collapses a stored weekly release-radar history item (see
`release_radar_dynamo.save_release_radar_week`) into the flat `RadarProfile`
shape the xomware.com `/music` hub expects. Kept separate from the handler so
it is unit-testable in isolation and carries no AWS/Spotify dependencies.

Stored release object shape (from the cron, normalized for storage)::

    {
      "albumName":   str,
      "artistName":  str,
      "albumType":   "album" | "single" | "compilation" | ...,
      "releaseDate": "YYYY-MM-DD" | "YYYY-MM" | "YYYY",
      "imageUrl":    str | None,
      "spotifyUrl":  str | None,
      ...
    }

Target frontend contract (pinned — do not drift)::

    {
      "releases": [{ "name", "artist", "albumArt", "url", "releaseDate", "type" }],
      "windowLabel": "This week",
      "updatedAt": "<iso>" | null,
    }

`type` is `'album' | 'single' | 'ep'`, mapped from the Spotify `album_type`.
"""

from typing import Any, Optional

WINDOW_LABEL = "This week"

# Spotify only exposes album / single / compilation as `album_type`; it has no
# distinct "ep" type, so EPs surface as `single` with several tracks. We expose
# only the three the frontend understands and default unknowns to 'single'.
_ALLOWED_TYPES = frozenset({"album", "single", "ep"})


def _map_release_type(album_type: Optional[str]) -> str:
    """Map a Spotify `album_type` to the frontend `'album'|'single'|'ep'`."""
    normalized = (album_type or "").strip().lower()
    if normalized in _ALLOWED_TYPES:
        return normalized
    # `compilation` and anything unexpected collapse to 'single' (safest
    # default for a non-album release).
    return "single"


def _flatten_release(release: dict) -> dict:
    """Map a stored release object to the frontend release shape.

    Defensive `.get()` throughout, mirroring `top_items_transform._flatten_track`:
    real stored items always carry these keys, but a malformed row must not blow
    up the whole response.
    """
    return {
        "name": release.get("albumName"),
        "artist": release.get("artistName"),
        "albumArt": release.get("imageUrl"),
        "url": release.get("spotifyUrl"),
        "releaseDate": release.get("releaseDate"),
        "type": _map_release_type(release.get("albumType") or release.get("album_type")),
    }


def flatten_public_release_radar(
    week_item: Optional[dict],
) -> dict[str, Any]:
    """
    Flatten the latest stored weekly radar item into the public contract.

    Args:
        week_item: A release-radar history item (`{releases, createdAt, ...}`),
            or None on a miss. None / missing `releases` yields an empty
            `releases` array and `updatedAt: null` (graceful degradation).

    Returns:
        The flat `RadarProfile` dict.
    """
    item = week_item or {}
    releases = item.get("releases") or []

    return {
        "releases": [_flatten_release(r) for r in releases if isinstance(r, dict)],
        "windowLabel": WINDOW_LABEL,
        "updatedAt": item.get("createdAt"),
    }
