# Plan: notification-kind-registry

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B1 (`notification-kind-registry`)
**Track**: B — Notifications Platform
**Status**: Done
**Created**: 2026-08-24
**Last updated**: 2026-08-24
**Scope size**: TBD — run `/plan notification-kind-registry` to size
**Repo(s) touched**: `xomify-backend`
**Branch**: `feature/notification-kind-registry`
**Wave**: 1
**Depends on**: _nothing — can start immediately_

---

## Summary

Kind registry, the fail-open notify() helper, and the coalescing mechanism.

## Approach

Registry maps kind -> default opt-in, title/body template, deep-link route, section. `notify(kind, email, **ctx)` writes the inbox row, checks per-kind opt-in, async-invokes notifications_send. Fail-open, mirroring `record_notification`. Rewrite notifications_send to validate against the registry instead of its hardcoded VALID_KINDS / OPT_IN_FLAG_BY_KIND pair. Coalescing (decision 11): kinds may declare a coalesce_key + window; share_listened and share_rated share key (actorEmail, shareId) on a 10-minute window. Needs a short-TTL pending row plus a 5-minute sweeper — NOT the daily cron_rate_reminder schedule.

## Affected Files / Components

- `lambdas/common/notification_kinds.py (new)`
- `lambdas/common/notify.py (new)`
- `lambdas/notifications_send/handler.py`

## Implementation Steps

_Stub — not yet planned. Run `/plan notification-kind-registry` to expand this into ordered, checkable steps._

- [ ] TBD

## Acceptance

_Stub — define with `/plan notification-kind-registry`._

---

## Epic context

Locked decisions live in the epic plan and must not be re-litigated here. See
`https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md` — decisions table, rows 1-11.


---

## Outcome

Landed on `feature/notification-kind-registry`.

| File | Change |
|------|--------|
| `lambdas/common/notification_kinds.py` | new — 16-kind registry |
| `lambdas/common/notify.py` | new — fail-open dispatch helper + coalescing |
| `lambdas/common/notification_pending_dynamo.py` | new — coalescing store |
| `lambdas/cron_notification_sweeper/handler.py` | new — 5-minute sweeper |
| `lambdas/notifications_send/handler.py` | rewired onto the registry |
| `tests/test_notification_kinds.py` | new — 13 tests |
| `tests/test_notify.py` | new — 12 tests |
| `tests/conftest.py` | 4 notification env vars added |

### Decisions taken during implementation

- **A pending table, not APNs `collapse_id`.** Collapse-id replaces the notification
  already in the tray, which fixes clutter but not the buzz — the second push still
  alerts. Coalescing only means anything if the first event is *held back*, and holding
  it requires somewhere to hold it.
- **Coalescing degrades to immediate send.** B1 ships before B6 provisions the table, so
  an unset `NOTIFICATION_PENDING_TABLE_NAME` falls through to sending uncoalesced. Losing
  coalescing is cosmetic; losing the notification is not.
- **Conditional write to claim the coalesce slot.** Two near-simultaneous events would
  otherwise both park and neither would ever send. Only one can create the row; the loser
  reads it back and merges.
- **`digest` now defaults OFF.** The old code read *every* absent flag as `True`, so a
  device row without `digestEnabled` was receiving a weekly push nobody opted into. This
  is the one kind where that default is actively wrong. Documented in the registry.
- **The sweeper needs its own 5-minute schedule.** It cannot ride `cron_rate_reminder`'s
  daily rule — a daily sweep would hold a lone "Sam listened" for up to 24 hours, which is
  worse than never sending it. Carried into B6.

### Test environment finding (pre-existing, not caused by this work)

The default `python3` here is 3.9.6 and the repo uses `X | Y` unions (3.10+), so a plain
`pytest` collapses into dozens of collection errors. It runs fine via the already-installed
`uv` and Homebrew `python3.13`:

```
uv run --python 3.13 --with pytest --with boto3 --with requests --with aiohttp \
       --with pyjwt --with cryptography --with pydantic python -m pytest -q
```

`--with-requirements requirements.txt` does NOT work — the pinned `cffi` fails to compile
against 3.13 headers.

**TRUE BASELINE: 660 passed, 0 failed.** Two earlier figures recorded here were wrong, both
because of this environment rather than the code:

| Reported | Cause | Actual |
|----------|-------|--------|
| "50 failed / 74 errors" | Python 3.9 vs 3.12 union syntax | not real |
| "14 failed / 600 passed" | `pydantic` missing from the ephemeral env | **660 passed, 0 failed** |

The suite is fully green. Worth putting that invocation in the README so nobody else
concludes otherwise.
