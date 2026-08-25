# Plan: notification-cron-producers

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B5 (`notification-cron-producers`)
**Track**: B — Notifications Platform
**Status**: Draft
**Created**: 2026-08-24
**Last updated**: 2026-08-24
**Scope size**: TBD — run `/plan notification-cron-producers` to size
**Repo(s) touched**: `xomify-backend`
**Branch**: `feature/notification-cron-producers`
**Wave**: 3
**Depends on**: `B2`, `B3`

---

## Summary

Push fan-out on the three existing crons, plus the new cron_rate_reminder.

## Approach

cron_wrapped / cron_release_radar: after generating each playlist, notify() with a SNEAK PEEK — top track name + artist + cover art in the body, deep link straight into the playlist. cron_favorites_reminder: push alongside its existing SES email. cron_rate_reminder (decision 9): scans xomify-share-interactions for shares received >=24h ago with neither queued nor rated; ONE reminder per share ever, idempotent via a REMINDED#<shareId> marker, daily schedule, no second nudge.

## Affected Files / Components

- `lambdas/cron_wrapped/`
- `lambdas/cron_release_radar/`
- `lambdas/cron_favorites_reminder/`
- `lambdas/cron_rate_reminder/ (new)`

## Implementation Steps

_Stub — not yet planned. Run `/plan notification-cron-producers` to expand this into ordered, checkable steps._

- [ ] TBD

## Acceptance

_Stub — define with `/plan notification-cron-producers`._

---

## Epic context

Locked decisions live in the epic plan and must not be re-litigated here. See
`https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md` — decisions table, rows 1-11.
