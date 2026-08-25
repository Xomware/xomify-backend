# Plan: notification-cron-producers

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B5 (`notification-cron-producers`)
**Track**: B — Notifications Platform
**Status**: Done (broadcast fan-out still deferred)
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

---

## Outcome

Suite: **14 failed / 646 passed** (baseline 14 / 600). 7 new tests.

| Producer | Kind | Notes |
|----------|------|-------|
| `cron_wrapped` | `wrapped_drop` | sneak peek + deep link to the playlist |
| `cron_release_radar` | `release_radar_drop` | sneak peek; **empty weeks are not notified** |
| `cron_favorites_reminder` | `favorites_reminder` | push alongside the existing SES email |
| `cron_rate_reminder` | `rate_reminder` | **new lambda** |

### The sneak peek

This is the part that was actually asked for. `notify.sneak_peek()` pulls name, artist and
cover art off a raw Spotify track object, so a drop reads *"Starting with Midnight City —
M83"* rather than *"Your Wrapped is ready"*. The route deep-links straight into the
playlist. Release Radar does not need the helper — its releases are already normalised
with `albumName` / `artistName` / `imageUrl`.

`_month_label()` turns `"2026-03"` into `"March"`. A month key is a storage detail, not
push copy.

### `cron_rate_reminder`

- **Window is `[24h, 48h)`.** The lower bound gives a share a day to land. The upper bound
  is what stops a daily scan re-examining the whole table forever — without it the cost
  grows without limit.
- **Latch before work, not after.** `mark_rate_reminded` is a conditional write on the
  share row, same trick as `mark_threshold_notified`. Acquiring it first means losing the
  race costs nothing; doing the reads first and *then* discovering another run owns the
  share wastes them.
- **Engagement means listened OR rated.** A rating with no recorded listen is still
  engagement, and nudging that person would be plainly wrong. Tested.
- **Capped at 200 per run**, so a pathological day degrades into several runs rather than
  one timeout that sends nothing.

### Best-effort placement

The favorites push sits **after** `send_favorites_reminder_email` and outside the
try/except that counts a failure. The email is what "sent" means for that cron — a push
failure must not cost someone the reminder they would otherwise have received, nor mark
the send failed.

### STILL DEFERRED: `admin_broadcasts_create`

Carried over from B4 and not resolved here. Fanning out to every user needs a users-table
scan; doing it inside the admin's request handler risks a timeout with no feedback. The
right shape is an async invoke into a dedicated fan-out lambda, which is really its own
small sub-feature. **It is the one notification kind in the registry with no producer.**
