"""
PUT /goals/set - Replace the caller's goal set.

Body: {"goals": [{goalId, metric, target, label, icon?}]}
Response: {"goals": [...]}

Whole-set replace: the client edits a short list and saves it. A partial-update
protocol would need delete tracking to handle removals, which is three
endpoints and a sync bug for no gain at four-to-twenty items.

PROGRESS IS NOT ACCEPTED. `current` and `completed` are derived from listening
history client-side; storing them would freeze a number that keeps moving for
the rest of the week.
"""

from __future__ import annotations

from typing import Any

from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.goals_dynamo import MAX_GOALS, replace_goals
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = "goals_set"

VALID_METRICS = {
    "minutes_listened",
    "new_artists",
    "genres_explored",
    "songs_from_top_artist",
    "unique_tracks",
}

LABEL_MAX = 80


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    email = get_caller_email(event)
    body = parse_body(event)

    raw = body.get("goals")
    if not isinstance(raw, list):
        raise ValidationError(
            message="goals must be a list",
            handler=HANDLER, function="handler", field="goals",
        )
    if len(raw) > MAX_GOALS:
        raise ValidationError(
            message=f"At most {MAX_GOALS} goals",
            handler=HANDLER, function="handler", field="goals",
        )

    cleaned: list[dict[str, Any]] = []
    for index, goal in enumerate(raw):
        if not isinstance(goal, dict):
            raise ValidationError(
                message=f"goals[{index}] must be an object",
                handler=HANDLER, function="handler", field="goals",
            )

        metric = goal.get("metric")
        if metric not in VALID_METRICS:
            raise ValidationError(
                message=f"goals[{index}].metric must be one of: {sorted(VALID_METRICS)}",
                handler=HANDLER, function="handler", field="metric",
            )

        try:
            target = int(goal.get("target"))
        except (TypeError, ValueError):
            raise ValidationError(
                message=f"goals[{index}].target must be a number",
                handler=HANDLER, function="handler", field="target",
            )
        if target <= 0:
            raise ValidationError(
                message=f"goals[{index}].target must be positive",
                handler=HANDLER, function="handler", field="target",
            )

        goal_id = str(goal.get("goalId") or "").strip()
        if not goal_id:
            raise ValidationError(
                message=f"goals[{index}].goalId is required",
                handler=HANDLER, function="handler", field="goalId",
            )

        label = str(goal.get("label") or "").strip()[:LABEL_MAX]
        cleaned.append({
            "goalId": goal_id,
            "metric": metric,
            "target": target,
            "label": label or f"{target} {metric.replace('_', ' ')}",
            "icon": goal.get("icon") or "target",
            "createdAt": goal.get("createdAt"),
        })

    log.info(f"goals_set: {email} saving {len(cleaned)} goal(s)")
    return success_response({"goals": replace_goals(email, cleaned)})
