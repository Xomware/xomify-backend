"""
GET /goals/get - The caller's weekly goals and week history.

Response:
    {
      "goals":   [{goalId, metric, target, label, icon, createdAt, updatedAt}],
      "history": [{weekStart, allMet, metCount, totalCount, recordedAt}]  # newest first
    }

Returns the DEFAULT goal set for a user who has never saved any, so a first
visit shows something to work toward rather than an empty screen. Defaults are
not persisted — they become real rows on the first save.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.errors import handle_errors
from lambdas.common.goals_dynamo import get_goals, get_history
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import get_caller_email, success_response

log = get_logger(__file__)

HANDLER = "goals_get"

#: Mirrors DEFAULT_GOALS in xomify-frontend/src/app/services/goals.service.ts.
#: Kept in step by hand — the list is four items and changes about never.
DEFAULT_GOALS: list[dict[str, Any]] = [
    {"goalId": "default-minutes", "metric": "minutes_listened", "target": 300,
     "label": "Listen for 5 hours", "icon": "headphones"},
    {"goalId": "default-artists", "metric": "new_artists", "target": 3,
     "label": "Discover 3 new artists", "icon": "mic"},
    {"goalId": "default-genres", "metric": "genres_explored", "target": 4,
     "label": "Explore 4 genres", "icon": "music-note"},
    {"goalId": "default-tracks", "metric": "unique_tracks", "target": 50,
     "label": "50 unique tracks", "icon": "trending-up"},
]


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    email = get_caller_email(event)

    goals = get_goals(email)
    if not goals:
        log.info(f"goals_get: {email} has none — returning defaults")
        goals = [dict(goal) for goal in DEFAULT_GOALS]

    return success_response({
        "goals": goals,
        "history": get_history(email),
    })
