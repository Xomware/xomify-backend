"""
Shared per-range top-items fetch (with partial-failure tolerance).

Extracted from `lambdas/user_top_items/handler.py` so both the auth-gated
`/user/top-items` handler and the public `/music/public-top-items` handler can
reuse the same Spotify fetch path WITHOUT duplicating any Spotify logic.

Per-range partial failure:
    Spotify can rate-limit or transiently fail any of the six (tracks +
    artists) x (short_term, medium_term, long_term) calls. We isolate each
    range so a single failure does not poison the whole response: the failing
    range's value is `null` and the caller receives `failed_ranges` with the
    union of failing range names. A partial response should NOT be cached, so
    the next call retries the failing ranges.
"""

import asyncio
from typing import Optional

import aiohttp

from lambdas.common.logger import get_logger
from lambdas.common.spotify import Spotify

log = get_logger(__file__)

_TIME_RANGES = ("short_term", "medium_term", "long_term")


def _empty_top_items_skeleton() -> dict:
    """Skeleton with every range present so the response shape is stable."""
    return {
        "tracks": {r: None for r in _TIME_RANGES},
        "artists": {r: None for r in _TIME_RANGES},
        "genres": {r: None for r in _TIME_RANGES},
    }


async def _safe_set_top_tracks(track_list) -> Optional[Exception]:
    """Run `track_list.set_top_tracks()` and swallow the exception (return it)."""
    try:
        await track_list.set_top_tracks()
        return None
    except Exception as err:  # noqa: BLE001 - intentional per-range isolation
        log.warning(
            f"top_items per-range failure kind=tracks term={track_list.term} err={err}"
        )
        return err


async def _safe_set_top_artists(artist_list) -> Optional[Exception]:
    """Run `artist_list.set_top_artists()` and swallow the exception (return it)."""
    try:
        await artist_list.set_top_artists()
        return None
    except Exception as err:  # noqa: BLE001 - intentional per-range isolation
        log.warning(
            f"top_items per-range failure kind=artists term={artist_list.term} err={err}"
        )
        return err


async def _fetch_top_items_with_partial_tolerance(user: dict) -> tuple[dict, list[str]]:
    """
    Fetch top items per-range, tolerating individual failures.

    Returns:
        (payload, failed_ranges)
        - payload has the standard `{tracks, artists, genres}` shape with
          `null` for any range that failed.
        - failed_ranges is the union of failing range names across tracks
          and artists (e.g. ["short_term", "medium_term"]). A failed
          artists range also nulls out genres for that range, since genres
          are derived from artists.
    """
    payload = _empty_top_items_skeleton()
    failed_ranges: set[str] = set()

    async with aiohttp.ClientSession() as session:
        spotify = Spotify(user, session)
        await spotify.aiohttp_initialize_top_items()

        track_lists = {
            "short_term": spotify.top_tracks_short,
            "medium_term": spotify.top_tracks_medium,
            "long_term": spotify.top_tracks_long,
        }
        artist_lists = {
            "short_term": spotify.top_artists_short,
            "medium_term": spotify.top_artists_medium,
            "long_term": spotify.top_artists_long,
        }

        # Fire all six requests in parallel; ordering matches our terms tuples
        # so we can map results back to range names.
        track_tasks = [_safe_set_top_tracks(track_lists[r]) for r in _TIME_RANGES]
        artist_tasks = [_safe_set_top_artists(artist_lists[r]) for r in _TIME_RANGES]
        track_errors, artist_errors = await asyncio.gather(
            asyncio.gather(*track_tasks),
            asyncio.gather(*artist_tasks),
        )

        for term, err in zip(_TIME_RANGES, track_errors):
            if err is None:
                payload["tracks"][term] = track_lists[term].track_list
            else:
                failed_ranges.add(term)

        for term, err in zip(_TIME_RANGES, artist_errors):
            if err is None:
                payload["artists"][term] = artist_lists[term].artist_list
                payload["genres"][term] = artist_lists[term].top_genres
            else:
                failed_ranges.add(term)
                # Genres are derived from artists, so null them too.

    return payload, sorted(failed_ranges)
