"""
GET /admin/view-as?email= - Read-only impersonation projection (admin only).

Returns a read-only view of what the target user sees, assembled from their
own (email-keyed) derived data. It does NOT use the target's Spotify refresh
token, so live Spotify-derived surfaces (top items, now-playing) are omitted
by design — see `note`.

Response:
{
  "email": "user@x.com",
  "profile": {"displayName", "avatar", "userId", "active",
              "spotifyConnected", "lastSeen"},
  "optIns": {"wrapped", "releaseRadar", "likesPublic", "favoritesReminder"},
  "recentVisits": [{"ts", "path"}],
  "favorites": [<favorites list rows for the current year>],
  "activeBroadcasts": [{"id", "title", "body", "activeUntil", "createdAt"}],
  "note": "..."
}
"""

from datetime import datetime, timezone

from lambdas.common.admin import require_admin
from lambdas.common.broadcasts_dynamo import get_active_broadcasts
from lambdas.common.dynamo_helpers import get_user_table_data
from lambdas.common.errors import NotFoundError, ValidationError, handle_errors
from lambdas.common.favorites_dynamo import get_lists_for_year
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import get_query_params, success_response
from lambdas.common.visits_dynamo import list_visits_for_user

log = get_logger(__file__)

HANDLER = "admin_view_as"

_VISITS_LIMIT = 20
_NOTE = (
    "Read-only projection assembled from the user's own email-keyed data. "
    "Live Spotify-derived data (top items, now playing) is not impersonated "
    "because it would require using the target's refresh token server-side."
)


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)
    params = get_query_params(event)

    email = params.get("email")
    if not email:
        raise ValidationError("email is required", handler=HANDLER, field="email")

    try:
        user = get_user_table_data(email)
    except NotFoundError:
        raise NotFoundError(
            message=f"No user found for {email}",
            handler=HANDLER,
            resource=email,
        )

    active = bool(user.get("active"))
    year = datetime.now(timezone.utc).year

    try:
        favorites = get_lists_for_year(email, year)
    except Exception as err:  # noqa: BLE001 - projection stays best-effort
        log.warning(f"view-as favorites load failed email={email}: {err}")
        favorites = []

    try:
        visit_rows = list_visits_for_user(email, limit=_VISITS_LIMIT)
    except Exception as err:  # noqa: BLE001
        log.warning(f"view-as visits load failed email={email}: {err}")
        visit_rows = []
    recent_visits = [
        {"ts": v.get("visitedAt") or v.get("ts"), "path": v.get("path")}
        for v in visit_rows
    ]

    active_broadcasts = [
        {
            "id": b.get("broadcastId"),
            "title": b.get("title"),
            "body": b.get("body"),
            "activeUntil": b.get("activeUntil"),
            "createdAt": b.get("createdAt"),
        }
        for b in get_active_broadcasts()
    ]

    log.info(f"admin_view_as by={admin_email} target={email}")

    return success_response({
        "email": email,
        "profile": {
            "displayName": user.get("displayName") or "",
            "avatar": user.get("avatar"),
            "userId": user.get("userId"),
            "active": active,
            "spotifyConnected": active and bool(user.get("refreshToken")),
            "lastSeen": user.get("lastSeen"),
        },
        "optIns": {
            "wrapped": bool(user.get("activeWrapped")),
            "releaseRadar": bool(user.get("activeReleaseRadar")),
            "likesPublic": bool(user.get("likes_public", True)),
            "favoritesReminder": active,
        },
        "recentVisits": recent_visits,
        "favorites": favorites,
        "activeBroadcasts": active_broadcasts,
        "note": _NOTE,
    })
