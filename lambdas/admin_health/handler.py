"""
GET /admin/health?windowHours= - API health rollup (admin only).

Aggregates the request-log over the requested window (default 24h).

Response:
{
  "windowHours": 24,
  "totalCalls": 1234,
  "errorCount": 12,
  "byRoute": [{"path": "/favorites/recommendations", "count": 90,
               "errors": 1, "p50ms": 42}],
  "recentErrors": [{"ts": "...", "path": "...", "status": 500,
                    "email": "...", "error": "..."}]
}
"""

from datetime import datetime, timedelta, timezone

from lambdas.common.admin import require_admin
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.request_log_dynamo import query_requests_since
from lambdas.common.utility_helpers import get_query_params, success_response

log = get_logger(__file__)

HANDLER = "admin_health"

_DEFAULT_WINDOW_HOURS = 24
_MAX_WINDOW_HOURS = 24 * 30
_RECENT_ERRORS_LIMIT = 50


def _p50(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return int(ordered[len(ordered) // 2])


def _window_hours(params: dict) -> int:
    raw = params.get("windowHours")
    if raw is None:
        return _DEFAULT_WINDOW_HOURS
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_HOURS
    return max(1, min(hours, _MAX_WINDOW_HOURS))


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)
    params = get_query_params(event)
    window_hours = _window_hours(params)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = query_requests_since(cutoff)

    total_calls = len(rows)
    error_count = 0
    by_route: dict[str, dict] = {}
    errors: list[dict] = []

    for row in rows:
        path = row.get("path") or "unknown"
        status = int(row.get("status") or 0)
        duration = int(row.get("durationMs") or 0)
        is_error = status >= 400

        bucket = by_route.setdefault(path, {"count": 0, "errors": 0, "_durations": []})
        bucket["count"] += 1
        bucket["_durations"].append(duration)
        if is_error:
            bucket["errors"] += 1
            error_count += 1
            errors.append({
                "ts": row.get("ts"),
                "path": path,
                "status": status,
                "email": row.get("email") or "",
                "error": row.get("error") or "",
            })

    by_route_list = [
        {
            "path": path,
            "count": data["count"],
            "errors": data["errors"],
            "p50ms": _p50(data["_durations"]),
        }
        for path, data in by_route.items()
    ]
    by_route_list.sort(key=lambda r: r["count"], reverse=True)

    errors.sort(key=lambda e: e.get("ts") or "", reverse=True)
    recent_errors = errors[:_RECENT_ERRORS_LIMIT]

    log.info(
        f"admin_health by={admin_email} window={window_hours}h "
        f"calls={total_calls} errors={error_count}"
    )

    return success_response({
        "windowHours": window_hours,
        "totalCalls": total_calls,
        "errorCount": error_count,
        "byRoute": by_route_list,
        "recentErrors": recent_errors,
    })
