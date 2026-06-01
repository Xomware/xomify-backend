"""
Flatten/slice transform for the public top-items endpoint.

Collapses the range-keyed `{tracks, artists, genres}` cache payload (which
stores raw Spotify `items`) into the flat, top-5, `short_term`-only shape the
xomware.com landing page expects. Kept separate from the handler so it is
unit-testable in isolation and carries no AWS/Spotify dependencies.

Target frontend contract (pinned — do not drift):
    {
      "topTracks":  [{ "name", "artist", "albumArt", "url" }],  // <=5
      "topArtists": [{ "name", "image", "url" }],               // <=5
      "topGenres":  [{ "genre", "count" }],                     // <=5
      "windowLabel": "Last 4 weeks",   // short_term
      "updatedAt": "<iso>" | null,      // from cache cachedAt
      "nowPlaying": null                // v2
    }
"""

from typing import Any, Optional

# v1 serves the short_term window only; the label is the human-readable
# equivalent Spotify uses for the ~4 week rolling window.
PUBLIC_RANGE = "short_term"
WINDOW_LABEL = "Last 4 weeks"

_MAX_ITEMS = 5


def _flatten_track(track: dict) -> dict:
    """Map a raw Spotify track object to the frontend track shape.

    Defensive `.get()` throughout: the conftest sample omits `album` /
    `external_urls`, while real Spotify payloads include them.
    """
    artists = track.get("artists") or []
    images = (track.get("album") or {}).get("images") or []
    return {
        "name": track.get("name"),
        "artist": ", ".join(a.get("name") for a in artists if a.get("name")),
        "albumArt": (images[0] or {}).get("url") if images else None,
        "url": (track.get("external_urls") or {}).get("spotify"),
    }


def _flatten_artist(artist: dict) -> dict:
    """Map a raw Spotify artist object to the frontend artist shape."""
    images = artist.get("images") or []
    return {
        "name": artist.get("name"),
        "image": (images[0] or {}).get("url") if images else None,
        "url": (artist.get("external_urls") or {}).get("spotify"),
    }


def _flatten_genres(genres: dict) -> list[dict]:
    """Convert a {genre: count} map to a top-5 [{genre, count}] list, desc."""
    if not isinstance(genres, dict):
        return []
    ranked = sorted(genres.items(), key=lambda kv: kv[1], reverse=True)
    return [{"genre": genre, "count": count} for genre, count in ranked[:_MAX_ITEMS]]


def flatten_public_top_items(
    cache_payload: Optional[dict],
    cached_at: Optional[str],
) -> dict[str, Any]:
    """
    Flatten the range-keyed cache payload into the public top-items contract.

    Reads `short_term` only, slices each list to <=5, maps to the frontend
    field names, and stamps `windowLabel`, `updatedAt`, and `nowPlaying`.

    Args:
        cache_payload: The `{tracks, artists, genres}` payload (range-keyed).
            None or missing ranges yield empty arrays (graceful degradation).
        cached_at: ISO timestamp of when the data was cached, or None.

    Returns:
        The flat public contract dict.
    """
    payload = cache_payload or {}

    tracks = (payload.get("tracks") or {}).get(PUBLIC_RANGE) or []
    artists = (payload.get("artists") or {}).get(PUBLIC_RANGE) or []
    genres = (payload.get("genres") or {}).get(PUBLIC_RANGE) or {}

    return {
        "topTracks": [_flatten_track(t) for t in tracks[:_MAX_ITEMS]],
        "topArtists": [_flatten_artist(a) for a in artists[:_MAX_ITEMS]],
        "topGenres": _flatten_genres(genres),
        "windowLabel": WINDOW_LABEL,
        "updatedAt": cached_at,
        "nowPlaying": None,
    }
