"""
GET /admin/users-list - User directory (admin only).

Response:
[
  {
    "email": "user@x.com",
    "displayName": "User",
    "lastSeen": "2026-07-28T12:00:00+00:00" | null,
    "optIns": {"wrapped": true, "releaseRadar": false,
               "likesPublic": true, "favoritesReminder": true},
    "spotifyConnected": true
  }
]

Opt-ins are read from the existing users-table enrollment attributes:
- wrapped           <- activeWrapped
- releaseRadar      <- activeReleaseRadar
- likesPublic       <- likes_public (default True)
- favoritesReminder <- active (the favorites-reminder cron targets active users;
                        there is no separate enrollment flag)
`spotifyConnected` is true when the user is active AND has a stored refresh token.
`lastSeen` is stamped by the request-log hook on each authed call.
"""

from lambdas.common.admin import require_admin
from lambdas.common.constants import USERS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "admin_users_list"


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)

    users = full_table_scan(USERS_TABLE_NAME)

    payload = []
    for user in users:
        active = bool(user.get("active"))
        payload.append({
            "email": user.get("email"),
            "displayName": user.get("displayName") or "",
            "lastSeen": user.get("lastSeen"),
            "optIns": {
                "wrapped": bool(user.get("activeWrapped")),
                "releaseRadar": bool(user.get("activeReleaseRadar")),
                "likesPublic": bool(user.get("likes_public", True)),
                "favoritesReminder": active,
            },
            "spotifyConnected": active and bool(user.get("refreshToken")),
        })

    payload.sort(key=lambda u: (u.get("lastSeen") or ""), reverse=True)

    log.info(f"admin_users_list by={admin_email} count={len(payload)}")
    return success_response(payload)
