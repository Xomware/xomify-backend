# Plan: notification-inbox-api

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B3 (`notification-inbox-api`)
**Track**: B — Notifications Platform
**Status**: Draft
**Created**: 2026-08-24
**Last updated**: 2026-08-24
**Scope size**: TBD — run `/plan notification-inbox-api` to size
**Repo(s) touched**: `xomify-backend`
**Branch**: `feature/notification-inbox-api`
**Wave**: 2
**Depends on**: `B1`

---

## Summary

xomify-notifications table plus the three inbox endpoints.

## Approach

PK email, SK ts#<rand8>; attrs kind, title, body, route, actorEmail, actorName, imageUrl, read, createdAt, ttl (90d). GET /notifications (paginated, newest first), POST /notifications/read (one or all), GET /notifications/unread-count. Distinct from xomify-notification-log, which is PK day, scan-based, and an admin send-log rather than a per-user feed. Both tables stay.

## Affected Files / Components

- `lambdas/common/notifications_dynamo.py (new)`
- `lambdas/notifications_feed/ (new)`
- `lambdas/notifications_read/ (new)`
- `lambdas/notifications_unread_count/ (new)`

## Implementation Steps

_Stub — not yet planned. Run `/plan notification-inbox-api` to expand this into ordered, checkable steps._

- [ ] TBD

## Acceptance

_Stub — define with `/plan notification-inbox-api`._

---

## Epic context

Locked decisions live in the epic plan and must not be re-litigated here. See
`https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md` — decisions table, rows 1-11.
