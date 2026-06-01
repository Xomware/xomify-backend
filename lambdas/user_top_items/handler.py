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
    The per-range fetch (with partial-failure tolerance) lives in
    `lambdas/common/top_items_fetch.py` so it can be shared with the public
    `/music/public-top-items` handler. See that module for the failure-isolation
    details.
"""

import asyncio
from typing import Any

from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.top_items_cache import get_cached, set_cached
from lambdas.common.top_items_fetch import (
    _TIME_RANGES,
    _empty_top_items_skeleton,
    _fetch_top_items_with_partial_tolerance,
)
from lambdas.common.utility_helpers import get_caller_email, success_response

log = get_logger(__file__)

HANDLER = "user_top_items"

# Re-exported for backwards compatibility with existing imports/tests.
__all__ = [
    "_TIME_RANGES",
    "_empty_top_items_skeleton",
    "_fetch_top_items_with_partial_tolerance",
    "handler",
]


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
