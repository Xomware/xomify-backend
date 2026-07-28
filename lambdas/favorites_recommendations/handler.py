"""
GET /favorites/recommendations?category=songs|albums|artists&listId=...&year=YYYY

Recommend up to 20 items (not already in the target list), ranked by the
caller's listening. Source is the caller's cached top-items (a cache miss fetches
live via the shared partial-tolerant fetch, then caches a fully-successful
result).

Scoring: aggregate across time ranges (short/medium/long); each range
contributes `score += (len - idx)` so higher-placed items score more. Duplicate
spotifyIds keep their max score. Items already in the target list are dropped.
Sorted score-desc, capped at 20.
"""

import asyncio
from typing import Any

from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.favorites_dynamo import get_list
from lambdas.common.logger import get_logger
from lambdas.common.top_albums import derive_albums_by_range
from lambdas.common.top_items_cache import get_cached, set_cached
from lambdas.common.top_items_fetch import _fetch_top_items_with_partial_tolerance
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    success_response,
)

log = get_logger(__file__)

HANDLER = "favorites_recommendations"

_TIME_RANGES = ("short_term", "medium_term", "long_term")
_VALID_CATEGORIES = ("songs", "albums", "artists")
_MAX_RECOMMENDATIONS = 20


def _artist_names(entity: dict) -> str:
    artists = entity.get("artists") or []
    names = [a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name")]
    return ", ".join(names)


def _image_url(entity: dict) -> str:
    images = entity.get("images") or []
    if images and isinstance(images[0], dict):
        return images[0].get("url") or ""
    return ""


def _normalize_track(track: dict) -> dict | None:
    spotify_id = track.get("id")
    if not spotify_id:
        return None
    album = track.get("album") if isinstance(track.get("album"), dict) else {}
    return {
        "spotifyId": spotify_id,
        "name": track.get("name", ""),
        "artist": _artist_names(track),
        "imageUrl": _image_url(album),
    }


def _normalize_artist(artist: dict) -> dict | None:
    spotify_id = artist.get("id")
    if not spotify_id:
        return None
    return {
        "spotifyId": spotify_id,
        "name": artist.get("name", ""),
        "artist": artist.get("name", ""),
        "imageUrl": _image_url(artist),
    }


def _normalize_album(album: dict) -> dict | None:
    spotify_id = album.get("spotifyId")
    if not spotify_id:
        return None
    return {
        "spotifyId": spotify_id,
        "name": album.get("name", ""),
        "artist": album.get("artist", ""),
        "imageUrl": album.get("imageUrl", ""),
    }


def _source_by_range(category: str, top_items: dict) -> dict:
    """Return {range: [raw entity]} for the requested category."""
    if category == "songs":
        return top_items.get("tracks") or {}
    if category == "artists":
        return top_items.get("artists") or {}
    # albums are derived from the top tracks per range
    return derive_albums_by_range(top_items.get("tracks") or {})


def _normalizer(category: str):
    if category == "songs":
        return _normalize_track
    if category == "artists":
        return _normalize_artist
    return _normalize_album


def _load_top_items(email: str) -> dict:
    cached = get_cached(email)
    if cached is not None:
        return cached
    log.info(f"favorites_recommendations cache=miss email={email}")
    user = get_user_table_data(email)
    payload, failed_ranges = asyncio.run(_fetch_top_items_with_partial_tolerance(user))
    if not failed_ranges:
        try:
            set_cached(email, payload)
        except Exception as err:  # noqa: BLE001 - cache write failure must not 500
            log.warning(f"favorites_recommendations cache write failed email={email} err={err}")
    return payload


def _excluded_ids(email: str, year: Any, list_id: str | None) -> set[str]:
    if not list_id or year is None:
        return set()
    row = get_list(email, year, list_id)
    if not row:
        return set()
    return {i.get("spotifyId") for i in (row.get("items") or []) if i.get("spotifyId")}


def _aggregate(category: str, top_items: dict, ranges: tuple[str, ...]) -> dict[str, dict]:
    """spotifyId -> {fields..., score} scored across the requested time ranges."""
    source = _source_by_range(category, top_items)
    normalize = _normalizer(category)
    scored: dict[str, dict] = {}

    for term in ranges:
        entities = source.get(term) or []
        if not isinstance(entities, list):
            continue
        length = len(entities)
        for idx, entity in enumerate(entities):
            if not isinstance(entity, dict):
                continue
            normalized = normalize(entity)
            if normalized is None:
                continue
            spotify_id = normalized["spotifyId"]
            contribution = length - idx
            existing = scored.get(spotify_id)
            if existing is None:
                normalized["score"] = contribution
                scored[spotify_id] = normalized
            else:
                existing["score"] = max(existing["score"], contribution)
    return scored


@handle_errors(HANDLER)
def handler(event, context):
    params = get_query_params(event)
    email = get_caller_email(event)

    category = params.get("category")
    if category not in _VALID_CATEGORIES:
        raise ValidationError(
            "category must be one of songs|albums|artists",
            handler=HANDLER,
            field="category",
        )

    # `range` scopes recommendations to a single listening window's top-items.
    # Defaults to short_term (recent taste). Previously recs blended all ranges.
    time_range = params.get("range") or "short_term"
    if time_range not in _TIME_RANGES:
        raise ValidationError(
            "range must be one of short_term|medium_term|long_term",
            handler=HANDLER,
            field="range",
        )

    list_id = params.get("listId")
    year_raw = params.get("year")
    year: int | None = None
    if year_raw is not None:
        try:
            year = int(year_raw)
        except (TypeError, ValueError):
            raise ValidationError("year must be an integer", handler=HANDLER, field="year")

    log.info(
        f"favorites_recommendations email={email} category={category} "
        f"listId={list_id} year={year} range={time_range}"
    )

    top_items = _load_top_items(email)
    scored = _aggregate(category, top_items, (time_range,))
    excluded = _excluded_ids(email, year, list_id)

    recommendations = [
        entry for spotify_id, entry in scored.items() if spotify_id not in excluded
    ]
    recommendations.sort(key=lambda e: e["score"], reverse=True)
    recommendations = recommendations[:_MAX_RECOMMENDATIONS]

    return success_response({
        "category": category,
        "listId": list_id,
        "range": time_range,
        "recommendations": recommendations,
    })
