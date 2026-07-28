"""
XOMIFY Cron Run Log DynamoDB Helpers
====================================
Backs the admin Crons sub-tab.

Table: xomify-cron-runs
- PK  `cronName`  [S]  — e.g. "wrapped", "release-radar"
- SK  `startedAt` [S]  — ISO8601 start time (sorts runs chronologically)
- attrs: finishedAt(ISO), status("ok"|"error"), error?(str),
         itemsProcessed?(int)

`record_cron_run(name, fn)` wraps a cron body: it times the run, persists a
row (fail-open), and re-raises any real cron error so the Lambda still fails
loudly. Reads (admin Crons) scan the small table and group by cronName.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import boto3
from boto3.dynamodb.conditions import Key

from lambdas.common.constants import AWS_DEFAULT_REGION, CRON_RUNS_TABLE_NAME
from lambdas.common.dynamo_helpers import full_table_scan
from lambdas.common.logger import get_logger

log = get_logger(__file__)
dynamodb = boto3.resource("dynamodb", region_name=AWS_DEFAULT_REGION)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_run(
    cron_name: str,
    started_at: str,
    finished_at: str,
    status: str,
    error: str | None,
    items_processed: int | None,
) -> None:
    if not CRON_RUNS_TABLE_NAME:
        return
    try:
        item = {
            "cronName": cron_name,
            "startedAt": started_at,
            "finishedAt": finished_at,
            "status": status,
        }
        if error:
            item["error"] = str(error)[:500]
        if items_processed is not None:
            item["itemsProcessed"] = int(items_processed)
        dynamodb.Table(CRON_RUNS_TABLE_NAME).put_item(Item=item)
    except Exception as err:  # noqa: BLE001 - instrumentation is best-effort
        log.warning(f"cron run write failed (ignored) cron={cron_name}: {err}")


def _extract_items(result: Any) -> int | None:
    """
    Best-effort itemsProcessed from a cron's return value. Cron handlers here
    return a `success_response` dict whose body is JSON; callers that want an
    explicit count should pass it via `record_cron_run(..., items=<n>)`.
    """
    if isinstance(result, int):
        return result
    return None


def _resolve_items(items: Any, result: Any) -> int | None:
    """`items` may be an int, a zero-arg callable (evaluated post-run), or None."""
    if callable(items):
        try:
            value = items()
        except Exception:  # noqa: BLE001
            value = None
    else:
        value = items
    if value is not None:
        return value
    return _extract_items(result)


def record_cron_run(
    cron_name: str,
    fn: Callable[[], Any],
    items: Any = None,
) -> Any:
    """
    Run `fn`, recording a cron-run row on completion. On success writes
    status="ok"; on exception writes status="error" (with the message) and
    re-raises. `items` is stored as itemsProcessed and may be an int, a
    zero-arg callable evaluated after `fn` (to read a count computed during
    the run), or None.
    """
    started_at = _iso_now()
    try:
        result = fn()
    except Exception as err:
        resolved = None if callable(items) else items
        _write_run(cron_name, started_at, _iso_now(), "error", str(err), resolved)
        raise
    _write_run(cron_name, started_at, _iso_now(), "ok", None, _resolve_items(items, result))
    return result


def list_runs_for_cron(cron_name: str, limit: int = 20) -> list[dict]:
    """Most-recent-first runs for a single cron."""
    if not CRON_RUNS_TABLE_NAME:
        return []
    try:
        resp = dynamodb.Table(CRON_RUNS_TABLE_NAME).query(
            KeyConditionExpression=Key("cronName").eq(cron_name),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get("Items", [])
    except Exception as err:  # noqa: BLE001
        log.warning(f"list_runs_for_cron failed cron={cron_name}: {err}")
        return []


def list_all_runs() -> list[dict]:
    """Every cron-run row (small table)."""
    if not CRON_RUNS_TABLE_NAME:
        return []
    return full_table_scan(CRON_RUNS_TABLE_NAME)
