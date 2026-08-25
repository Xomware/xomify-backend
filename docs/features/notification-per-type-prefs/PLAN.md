# Plan: notification-per-type-prefs

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B2 (`notification-per-type-prefs`)
**Track**: B — Notifications Platform
**Status**: Done
**Created**: 2026-08-24
**Last updated**: 2026-08-24
**Scope size**: TBD — run `/plan notification-per-type-prefs` to size
**Repo(s) touched**: `xomify-backend`
**Branch**: `feature/notification-per-type-prefs`
**Wave**: 2
**Depends on**: `B1`

---

## Summary

One opt-in boolean per kind on the device-token record.

## Approach

Absent flag reads as the registry default, so existing rows keep working with no backfill (decision 3). notifications_register accepts the full preference map. 14 kinds across three sections — see the epic plan's B2 table.

## Affected Files / Components

- `lambdas/common/device_tokens_dynamo.py`
- `lambdas/notifications_register/handler.py`

## Implementation Steps

_Stub — not yet planned. Run `/plan notification-per-type-prefs` to expand this into ordered, checkable steps._

- [ ] TBD

## Acceptance

_Stub — define with `/plan notification-per-type-prefs`._

---

## Epic context

Locked decisions live in the epic plan and must not be re-litigated here. See
`https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md` — decisions table, rows 1-11.

---

## Outcome

Landed on `feature/notification-kind-registry` (same branch as B1 — they are one
coherent change to the device-token contract).

| File | Change |
|------|--------|
| `lambdas/common/notification_kinds.py` | `effective_preferences()`, `sanitize_preferences()`, `VALID_FLAGS` |
| `lambdas/common/device_tokens_dynamo.py` | `upsert_token` writes flags sparsely, per-flag |
| `lambdas/notifications_register/handler.py` | accepts `preferences` map; returns the effective map |
| `tests/test_notification_preferences.py` | new — 10 tests |
| `tests/test_notifications_register.py` | 3 tests updated for the new contract |

### The invariant this sub-feature exists to protect

**Registration writes only the flags the client actually sent.** A blanket write of all
sixteen booleans would stamp today's defaults onto every device row, and
`is_opted_in`'s absent-means-default fallback — the entire no-backfill migration story —
would be dead the moment any client registered. Two tests defend this directly:
`test_upsert_with_no_preferences_touches_no_flags` and
`test_register_passes_only_explicit_flags_through`.

### Deliberate contract changes

- **Absent is no longer coerced to `True`.** `_as_bool` now returns `None` for a missing
  flag, so "the client did not mention this" stays distinct from "the client said yes".
  Three existing `notifications_register` tests asserted the old coercion and were updated.
- **The response echoes stored state, not the request.** It returns the effective map read
  back from the row (`ReturnValues="ALL_NEW"`), so one call renders all sixteen Settings
  toggles without the client needing to know any defaults.
- **Unknown flags are dropped, not written.** A client typo would otherwise persist as a
  meaningless attribute forever — the row has no schema to reject it.

### Implementation note

Expression placeholders are indexed (`#p0`, `:p0`, …) rather than derived from the flag
name. Several flags share a prefix, and DynamoDB requires unique expression names per
statement — name-derived placeholders would collide.
Covered by `test_flag_placeholders_are_unique`.
