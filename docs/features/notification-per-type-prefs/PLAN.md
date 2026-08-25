# Plan: notification-per-type-prefs

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B2 (`notification-per-type-prefs`)
**Track**: B — Notifications Platform
**Status**: Draft
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
