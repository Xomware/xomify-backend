# Plan: notification-interaction-producers

**Epic**: [xomify-relaunch](https://github.com/Xomware/xomify-frontend/blob/master/docs/features/xomify-relaunch/PLAN.md)
**Sub-feature ID**: B4 (`notification-interaction-producers`)
**Track**: B — Notifications Platform
**Status**: Done (9 of 10 — broadcast deferred, see below)
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

---

## Outcome

Suite: **14 failed / 639 passed** (baseline 14 / 600). 10 new tests.

| Producer | Kind | Recipient |
|----------|------|-----------|
| `shares_create` | `share_received` | fan-out to the author's accepted friends |
| `shares_comments_create` | `share_comment` | the share author |
| `shares_reactions_toggle` | `share_reaction` | the share author, **on add only** |
| `shares_listened` | `share_listened` | the share author (coalescing) |
| `shares_react` (rated) | `share_rated` | the share author (coalescing) |
| `friends_request` | `friend_request` | the target |
| `friends_accept` | `friend_accepted` | the original requester |
| `invites_accept` | `invite_accepted` | the inviter |

### Judgement calls

- **`shares_create` fans out.** A share is a friends-graph broadcast, not an addressed
  message — there is no recipient field. `notify_friends_of` caps at 100 and filters to
  `status == "accepted"`. That filter is load-bearing: `list_all_friends_for_user` returns
  the whole partition, so an unfiltered fan-out would push to people who declined or
  **blocked** you. Directly tested.
- **Group-only shares are skipped.** `share_received` says "someone sent you a song"; a
  group post is not that, and Groups has no client UI any more.
- **Reactions fire on ADD only.** Pushing on both edges of a toggle is a notification
  machine gun.
- **Reaction slugs are mapped to glyphs.** Reactions are stored as slugs (`fire`,
  `mind_blown`), so the push body needed `REACTION_EMOJI` — "Sam reacted fire" is not a
  sentence. Caught by a test, not by reading.
- **Failed writes notify nobody.** `friends_request` only notifies when
  `send_friend_request` returned True; a failed write must not tell the target someone tried.
- **`author_create` listens are skipped** in `shares_listened` — that source is
  `shares_create` marking its own author as a listener. `notify()` would suppress the
  self-case anyway, but skipping early avoids a pointless profile read.
- **Display names never leak an address.** `display_name_for` falls back to the email's
  local part, so a lock screen shows "dominick", not "dominick@…".

### NOT wired: `invites_create`

An invite is a URL/code handed to someone who is not on the platform yet. There is no
account to notify. `invite_received` stays in the registry for a future in-app invite
flow, but no producer can fire it today.

### DEFERRED: `admin_broadcasts_create`

Broadcasting to every user means scanning the users table and fanning out inside a request
handler — a timeout waiting to happen as the user base grows, and the admin gets no
feedback when it stalls. It belongs behind an async invoke or a cron, alongside the B5
producers. Moved to B5.
