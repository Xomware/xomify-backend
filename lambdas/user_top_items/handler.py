"""
GET /user/top-items - Return the signed-in user's top tracks, artists, genres
(live, daily-cached).

Caller identity comes from the authorizer context (per-user JWT) — see
`lambdas/common/utility_helpers.get_caller_email`. The endpoint is gated by the
custom authorizer in production; if the email cannot be resolved the helper
raises `MissingCallerIdentityError` (HTTP 401).

Cache (sub-feature 2a):
    - One DDB row per user keyed by email.
    - Handler-side freshness gate is `cachedAt.date() == today_utc.date()`
      (epic Q7) — DDB native TTL is a janitor only.
    - On a hit we return immediately with no Spotify call.
    - On a miss we fetch live from Spotify and write the cache only on a
      *fully successful* response.

Per-range partial failure:
    Spotify can rate-limit or transiently fail any of the six (tracks +
    artists) x (short_term, medium_term, long_term) calls. We isolate each
    range so a single failure does not poison the whole response: the failing
    range's value is `null` and the response carries `meta.failed_ranges` with
    the union of failing range names. A partial response is NOT cached, so the
    next call retries the failing ranges.
"""

import asyncio
from typing import Any, Optional

import aiohttp

from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.spotify import Spotify
from lambdas.common.top_items_cache import get_cached, set_cached
from lambdas.common.utility_helpers import get_caller_email, success_response

log = get_logger(__file__)

HANDLER = "user_top_items"

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


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    caller_email = get_caller_email(event)

    cached = get_cached(caller_email)
    if cached is not None:
        log.info(f"user_top_items cache=hit email={caller_email}")
        return success_response(cached)

    log.info(f"user_top_items cache=miss email={caller_email}")
    user = get_user_table_data(caller_email)

    payload, failed_ranges = asyncio.run(
        _fetch_top_items_with_partial_tolerance(user)
    )

    if not failed_ranges:
        try:
            set_cached(caller_email, payload)
        except Exception as err:  # noqa: BLE001 - cache write failure must not 500
            log.warning(
                f"user_top_items cache write failed email={caller_email} err={err}"
            )
    else:
        log.info(
            f"user_top_items partial response email={caller_email} "
            f"failed_ranges={failed_ranges} (skipping cache write)"
        )

    response_body: dict = dict(payload)
    if failed_ranges:
        response_body["meta"] = {"failed_ranges": failed_ranges}

    return success_response(response_body)
