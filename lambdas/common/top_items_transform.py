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
      "windowLabel": "Last 4 weeks",   // per requested range (see below)
      "updatedAt": "<iso>" | null,      // from cache cachedAt
      "nowPlaying": null                // v2
    }

The endpoint accepts an optional `?range=` ∈ {short_term, medium_term,
long_term}; the cache stores all three. `flatten_public_top_items` reads the
requested range and stamps the matching `windowLabel`. An absent/invalid range
defaults to `short_term` (the handler clamps + logs before calling here).
"""

from typing import Any, Optional

# Default range when the caller omits `?range=` or sends an invalid value.
PUBLIC_RANGE = "short_term"

# Human-readable window labels per Spotify range. short_term is the ~4 week
# rolling window, medium_term ~6 months, long_term is all-time.
RANGE_WINDOW_LABELS = {
    "short_term": "Last 4 weeks",
    "medium_term": "Last 6 months",
    "long_term": "All time",
}

# The set of ranges the cache stores and the endpoint will serve.
VALID_RANGES = frozenset(RANGE_WINDOW_LABELS.keys())

# Back-compat alias: previously the only label, now the short_term label.
WINDOW_LABEL = RANGE_WINDOW_LABELS[PUBLIC_RANGE]

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
    range_key: str = PUBLIC_RANGE,
) -> dict[str, Any]:
    """
    Flatten the range-keyed cache payload into the public top-items contract.

    Reads the requested `range_key`, slices each list to <=5, maps to the
    frontend field names, and stamps `windowLabel`, `updatedAt`, and
    `nowPlaying`.

    Args:
        cache_payload: The `{tracks, artists, genres}` payload (range-keyed).
            None or missing ranges yield empty arrays (graceful degradation).
        cached_at: ISO timestamp of when the data was cached, or None.
        range_key: One of `VALID_RANGES`. Anything else falls back to
            `PUBLIC_RANGE` (short_term) — the handler is expected to clamp +
            log invalid ranges, but we defend here too so the transform never
            keys the cache on a bogus range.

    Returns:
        The flat public contract dict.
    """
    payload = cache_payload or {}

    if range_key not in VALID_RANGES:
        range_key = PUBLIC_RANGE

    tracks = (payload.get("tracks") or {}).get(range_key) or []
    artists = (payload.get("artists") or {}).get(range_key) or []
    genres = (payload.get("genres") or {}).get(range_key) or {}

    return {
        "topTracks": [_flatten_track(t) for t in tracks[:_MAX_ITEMS]],
        "topArtists": [_flatten_artist(a) for a in artists[:_MAX_ITEMS]],
        "topGenres": _flatten_genres(genres),
        "windowLabel": RANGE_WINDOW_LABELS[range_key],
        "updatedAt": cached_at,
        "nowPlaying": None,
    }
