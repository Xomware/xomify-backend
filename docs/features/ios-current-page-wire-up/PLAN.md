---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 2c
repo: xomify-ios
---

# ios-current-page-wire-up

> **Status: Stub.** This is a placeholder. Run `/plan ios-current-page-wire-up` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Point "Top 25 — Last 4 Weeks (Current)" page at `GET /user/top-items` instead of `GET /wrapped/all`.
- Wrapped page (the historical snapshot view) stays on `/wrapped/all`.

## Repo
xomify-ios

## Dependencies
(2a-infra) AND (0d)

## Exit criteria
iOS "Last 4 Weeks (Current)" page shows top items refreshed within the last UTC day. Wrapped page unchanged.

## Notes
- Open action item from epic: path to iOS "Top 25 — Last 4 Weeks (Current)" view — grep at execution.
- Requires TestFlight build + manual smoke — human gate.
