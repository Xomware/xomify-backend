"""
Daily top-items cache helper.

Backs the `/user/top-items` endpoint (epic Track 2 / sub-feature 2a). Spotify's
`/me/top/*` is computed on a rolling daily window, so we cache one row per user
per day to keep it to a single Spotify hit per user per UTC day (epic Q7).

DDB native `TTL` eviction has up to 48h of lag, so we additionally gate on the
`cachedAt` ISO timestamp inside `get_cached`. The `ttl` attribute is used purely
as a janitor for inactive users — never as the freshness signal at read time.

The underlying table is provisioned by sub-feature (2a-infra) in
xomify-infrastructure. The constant `TOP_ITEMS_CACHE_TABLE_NAME` resolves the
table name from the environment so this module is no-op-importable in tests
even when no table exists.
"""

from datetime import datetime, time, timedelta, timezone
from typing import Optional

from boto3.dynamodb.conditions import Key  # noqa: F401  (kept for parity with other helpers)

from lambdas.common.constants import TOP_ITEMS_CACHE_TABLE_NAME
from lambdas.common.dynamo_helpers import dynamodb
from lambdas.common.errors import DynamoDBError
from lambdas.common.logger import get_logger

log = get_logger(__file__)

# Janitor TTL for inactive users — keep rows around for a week past the next
# midnight boundary so a user who comes back the day after still benefits from
# the previous-day cache being evicted *only* by the explicit handler-side
# `cachedAt` gate, not by a race with TTL.
_TTL_JANITOR_DAYS = 7


def _today_utc_date():
    """Return today's date in UTC. Indirected for ease of patching in tests."""
    return datetime.now(timezone.utc).date()


def _next_midnight_utc_epoch() -> int:
    """Epoch seconds at the next UTC midnight from now."""
    now = datetime.now(timezone.utc)
    next_midnight = datetime.combine(
        now.date() + timedelta(days=1), time.min, tzinfo=timezone.utc
    )
    return int(next_midnight.timestamp())


def _parse_cached_at(value) -> Optional[datetime]:
    """
    Parse a stored cachedAt back into a tz-aware datetime, tolerating a
    trailing 'Z' (which `datetime.fromisoformat` only accepts on >= 3.11) and
    naive timestamps (assumed UTC).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.rstrip("Z") if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_cached(email: str) -> Optional[dict]:
    """
    Return today's cached top items for `email`, or None on miss.

    Returns the `{tracks, artists, genres}` payload exactly as it was stored
    by `set_cached`. Returns None when:
        - no row exists for the user
        - the row exists but `cachedAt.date() < today_utc.date()`
          (TTL hasn't fired yet but the row is stale by our day-bucket rule)
        - the row exists but `cachedAt` is missing/malformed
    """
    if not email:
        return None
    try:
        table = dynamodb.Table(TOP_ITEMS_CACHE_TABLE_NAME)
        response = table.get_item(Key={"email": email})
    except Exception as err:
        log.error(f"top_items_cache.get_cached DDB error for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="get_cached",
            table=TOP_ITEMS_CACHE_TABLE_NAME,
        )

    item = response.get("Item")
    if not item:
        log.info(f"top_items_cache miss email={email} reason=no_row")
        return None

    cached_at = _parse_cached_at(item.get("cachedAt"))
    if cached_at is None:
        log.info(f"top_items_cache miss email={email} reason=missing_cachedAt")
        return None

    if cached_at.date() < _today_utc_date():
        log.info(
            f"top_items_cache miss email={email} reason=stale "
            f"cachedAt={cached_at.isoformat()}"
        )
        return None

    payload = {
        "tracks": item.get("tracks") or {},
        "artists": item.get("artists") or {},
        "genres": item.get("genres") or {},
    }
    log.info(f"top_items_cache hit email={email} cachedAt={cached_at.isoformat()}")
    return payload


def set_cached(email: str, top_items: dict) -> None:
    """
    Write `top_items` to the cache for `email`.

    `top_items` is expected to be the `{tracks, artists, genres}` shape
    returned by `Spotify.get_top_items_for_api()`. `cachedAt` is set to the
    current UTC time; `ttl` is set to the next UTC-midnight boundary plus
    `_TTL_JANITOR_DAYS` so DDB only purges the row well after our handler-side
    freshness gate has stopped serving it.
    """
    if not email:
        log.warning("top_items_cache.set_cached called with empty email; skipping")
        return
    if not isinstance(top_items, dict):
        log.warning("top_items_cache.set_cached called with non-dict payload; skipping")
        return

    cached_at = datetime.now(timezone.utc).isoformat()
    ttl_epoch = _next_midnight_utc_epoch() + (_TTL_JANITOR_DAYS * 24 * 3600)

    item = {
        "email": email,
        "tracks": top_items.get("tracks") or {},
        "artists": top_items.get("artists") or {},
        "genres": top_items.get("genres") or {},
        "cachedAt": cached_at,
        "ttl": ttl_epoch,
    }

    try:
        table = dynamodb.Table(TOP_ITEMS_CACHE_TABLE_NAME)
        table.put_item(Item=item)
    except Exception as err:
        log.error(f"top_items_cache.set_cached DDB error for {email}: {err}")
        raise DynamoDBError(
            message=str(err),
            function="set_cached",
            table=TOP_ITEMS_CACHE_TABLE_NAME,
        )

    log.info(
        f"top_items_cache write email={email} cachedAt={cached_at} ttl={ttl_epoch}"
    )
