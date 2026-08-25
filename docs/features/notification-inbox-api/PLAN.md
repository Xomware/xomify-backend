# Plan: notification-inbox-api

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B3 (`notification-inbox-api`)
**Track**: B — Notifications Platform
**Status**: Done
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

---

## Outcome

| File | Change |
|------|--------|
| `lambdas/common/notifications_dynamo.py` | new — inbox store |
| `lambdas/notifications_feed/handler.py` | new — `GET /notifications` |
| `lambdas/notifications_read/handler.py` | new — `POST /notifications/read` |
| `lambdas/notifications_unread_count/handler.py` | new — `GET /notifications/unread-count` |
| `lambdas/common/notify.py` | writes the inbox row before dispatching the push |
| `tests/test_notifications_inbox.py` | new — 19 tests |

Suite: **14 failed / 629 passed** (baseline 14 / 600 — nothing broken, +29).

### Design decisions

- **The SK does the sorting.** `tsId` is `"<iso8601>#<rand8>"`. ISO8601 sorts
  chronologically and lexicographically at once, so `ScanIndexForward=False` gives
  newest-first with no sort-key gymnastics and paging is a plain `ExclusiveStartKey`.
  The `#<rand8>` suffix exists purely so two notifications written in the same
  millisecond cannot collide.
- **Inbox and push are independent.** The inbox row is written even when the kind is
  muted, and even when the user has no device at all. Muting a push means "do not
  interrupt me", not "hide this from my history" — and web has no APNs token whatsoever,
  so gating the inbox on push delivery would leave every web user with a permanently
  empty inbox.
- **Self-notification writes nothing at all**, inbox included. You do not need a history
  entry for your own comment.
- **`mark_all_read` is bounded** at 300. An unbounded update loop is how a lambda finds
  its 15-minute timeout; a user past the cap marks the rest on a second call, which is a
  much better failure mode than a half-finished sweep reporting success.
- **`count_unread` follows pagination.** A single query's `Count` covers only that page —
  stopping at the first response silently undercounts the badge.
- **Not a GSI on the send log.** `xomify-notification-log` is PK `day`, scan-read, and
  answers "what did we send yesterday?" for the admin view. Indexing `toEmail` onto it
  would produce a send-log with an index, not an inbox with mutable read state.

### Deferred

`count_unread` applies its filter after the read, so it still reads the partition. At
90-day retention and one user's traffic that is cheap. If it stops being cheap the fix is
a sparse GSI over unread items — noted, not built.
