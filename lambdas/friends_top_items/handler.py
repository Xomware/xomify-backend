"""
GET /friends/top-items?email=<friend> - A friend's top tracks, artists, genres.

Gated on an accepted friendship AND the subject's `topItems` visibility.

CACHE-ONLY, deliberately. `/user/top-items` falls back to fetching from Spotify
on a cold cache; this does not. Fetching would spend the SUBJECT's Spotify
budget because someone else looked at their profile, and would let a friend
drive another account's API usage. A cold cache returns `cached: false` with no
items, and the client shows "nothing yet" -- the subject's own next visit fills
it.
"""

from lambdas.common.errors import handle_errors
from lambdas.common.friend_visibility_gate import assert_can_read
from lambdas.common.logger import get_logger
from lambdas.common.top_albums import derive_albums_by_range
from lambdas.common.top_items_cache import get_cached
from lambdas.common.utility_helpers import (
    get_caller_email,
    get_query_params,
    success_response,
)

log = get_logger(__file__)

HANDLER = "friends_top_items"


@handle_errors(HANDLER)
def handler(event, context):
    caller_email = get_caller_email(event)
    subject_email = (get_query_params(event) or {}).get("email")

    assert_can_read(caller_email, subject_email, "topItems", HANDLER)

    cached = get_cached(subject_email)
    if cached is None:
        log.info(f"friends_top_items cache=miss email={subject_email} (not fetching)")
        return success_response({
            "email": subject_email,
            "cached": False,
            "tracks": {},
            "artists": {},
            "genres": {},
            "albums": {},
        })

    log.info(f"friends_top_items cache=hit email={subject_email}")
    enriched = dict(cached)
    enriched["albums"] = derive_albums_by_range(cached.get("tracks") or {})
    enriched["email"] = subject_email
    enriched["cached"] = True
    return success_response(enriched)
