# Plan: notification-interaction-producers

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B4 (`notification-interaction-producers`)
**Track**: B — Notifications Platform
**Status**: Draft
**Created**: 2026-08-24
**Last updated**: 2026-08-24
**Scope size**: TBD — run `/plan notification-interaction-producers` to size
**Repo(s) touched**: `xomify-backend`
**Branch**: `feature/notification-interaction-producers`
**Wave**: 3
**Depends on**: `B2`, `B3`

---

## Summary

Wire notify() into the ten interaction lambdas that currently notify nobody.

## Approach

Every call fire-and-forget — a failed notification must never fail the interaction. Self-notification suppressed. shares_react keeps its existing queue_threshold latch and gains share_rated.

## Affected Files / Components

- `lambdas/shares_create/`
- `lambdas/shares_comments_create/`
- `lambdas/shares_reactions_toggle/`
- `lambdas/shares_listened/`
- `lambdas/shares_react/`
- `lambdas/friends_request/`
- `lambdas/friends_accept/`
- `lambdas/invites_create/`
- `lambdas/invites_accept/`
- `lambdas/admin_broadcasts_create/`

## Implementation Steps

_Stub — not yet planned. Run `/plan notification-interaction-producers` to expand this into ordered, checkable steps._

- [ ] TBD

## Acceptance

_Stub — define with `/plan notification-interaction-producers`._

---

## Epic context

Locked decisions live in the epic plan and must not be re-litigated here. See
`https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md` — decisions table, rows 1-11.
