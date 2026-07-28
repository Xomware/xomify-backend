"""
GET /admin/crons - Cron run history (admin only).

Response:
[
  {
    "cronName": "wrapped",
    "lastRun": {"startedAt": "...", "finishedAt": "...",
                "status": "ok", "error": null, "itemsProcessed": 3},
    "recentRuns": [{"startedAt": "...", "finishedAt": "...",
                    "status": "ok", "error": null, "itemsProcessed": 3}]
  }
]

Grouped from the xomify-cron-runs table. `recentRuns` is newest-first, capped.
Crons that have never recorded a run simply don't appear.
"""

from lambdas.common.admin import require_admin
from lambdas.common.cron_runs_dynamo import list_all_runs
from lambdas.common.errors import handle_errors
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import success_response

log = get_logger(__file__)

HANDLER = "admin_crons"

_RECENT_RUNS_LIMIT = 20


def _project(run: dict) -> dict:
    return {
        "startedAt": run.get("startedAt"),
        "finishedAt": run.get("finishedAt"),
        "status": run.get("status"),
        "error": run.get("error"),
        "itemsProcessed": run.get("itemsProcessed"),
    }


@handle_errors(HANDLER)
def handler(event, context):
    admin_email = require_admin(event)

    runs = list_all_runs()

    grouped: dict[str, list[dict]] = {}
    for run in runs:
        name = run.get("cronName")
        if not name:
            continue
        grouped.setdefault(name, []).append(run)

    payload = []
    for name, cron_runs in grouped.items():
        cron_runs.sort(key=lambda r: r.get("startedAt") or "", reverse=True)
        recent = [_project(r) for r in cron_runs[:_RECENT_RUNS_LIMIT]]
        payload.append({
            "cronName": name,
            "lastRun": recent[0] if recent else None,
            "recentRuns": recent,
        })

    payload.sort(key=lambda c: c["cronName"])

    log.info(f"admin_crons by={admin_email} crons={len(payload)}")
    return success_response(payload)
