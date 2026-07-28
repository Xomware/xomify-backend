"""
Derived top-albums.

Spotify has no `/me/top/albums` endpoint, so we derive albums from the user's
top *tracks* per time range: group a range's raw Spotify track objects by
`track.album.id`, count how many top tracks belong to each album, and rank the
albums by that frequency (ties broken by first-seen order).

Every field access is defensive `.get()` — the raw track shape can vary and some
fixtures/tracks omit `album` entirely (those tracks are skipped).
"""

from typing import Any

from lambdas.common.logger import get_logger

log = get_logger(__file__)

_TIME_RANGES = ("short_term", "medium_term", "long_term")


def _album_image_url(album: dict) -> str:
    images = album.get("images") or []
    if images and isinstance(images[0], dict):
        return images[0].get("url") or ""
    return ""


def _track_artist_names(track: dict) -> str:
    artists = track.get("artists") or []
    names = [a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")]
    return ", ".join(names)


def _derive_albums(tracks: Any) -> list[dict]:
    """Group one range's raw tracks into ranked albums."""
    if not isinstance(tracks, list):
        return []

    albums: dict[str, dict] = {}
    order = 0

    for track in tracks:
        if not isinstance(track, dict):
            continue
        album = track.get("album")
        if not isinstance(album, dict):
            continue
        album_id = album.get("id")
        if not album_id:
            continue

        if album_id not in albums:
            albums[album_id] = {
                "spotifyId": album_id,
                "name": album.get("name", ""),
                "artist": _track_artist_names(track),
                "imageUrl": _album_image_url(album),
                "trackCount": 0,
                "_order": order,
            }
            order += 1
        albums[album_id]["trackCount"] += 1

    ranked = sorted(albums.values(), key=lambda a: (-a["trackCount"], a["_order"]))
    for album in ranked:
        album.pop("_order", None)
    return ranked


def derive_albums_by_range(tracks_by_range: dict) -> dict:
    """
    Return `{short_term, medium_term, long_term}` each mapping to a ranked list
    of Album dicts derived from that range's top tracks.

    Album = {spotifyId, name, artist, imageUrl, trackCount}.
    """
    source = tracks_by_range if isinstance(tracks_by_range, dict) else {}
    return {term: _derive_albums(source.get(term)) for term in _TIME_RANGES}
