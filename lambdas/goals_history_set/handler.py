"""
POST /goals/history-set - Record one week's outcome.

Body: {"weekStart": "YYYY-MM-DD", "allMet": bool, "metCount": int, "totalCount": int}
Response: the stored entry.

Upsert keyed on `weekStart`: a week is re-evaluated every time the user opens
the page while it is still running, and appending would leave one row per visit
for the same seven days.
"""

from __future__ import annotations

import re
from typing import Any

from lambdas.common.errors import handle_errors, ValidationError
from lambdas.common.goals_dynamo import upsert_week
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import (
    get_caller_email,
    parse_body,
    success_response,
)

log = get_logger(__file__)

HANDLER = "goals_history_set"

_WEEK_START = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@handle_errors(HANDLER)
def handler(event: dict, context: Any) -> dict:
    email = get_caller_email(event)
    body = parse_body(event)

    week_start = str(body.get("weekStart") or "").strip()
    if not _WEEK_START.match(week_start):
        raise ValidationError(
            message="weekStart must be an ISO date (YYYY-MM-DD)",
            handler=HANDLER, function="handler", field="weekStart",
        )

    def _count(field: str) -> int:
        try:
            value = int(body.get(field, 0))
        except (TypeError, ValueError):
            raise ValidationError(
                message=f"{field} must be a number",
                handler=HANDLER, function="handler", field=field,
            )
        return max(0, value)

    entry = upsert_week(email, {
        "weekStart": week_start,
        "allMet": bool(body.get("allMet")),
        "metCount": _count("metCount"),
        "totalCount": _count("totalCount"),
    })
    return success_response(entry)
