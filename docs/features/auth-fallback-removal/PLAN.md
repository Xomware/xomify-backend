---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 1l
repo: xomify-backend
---

# auth-fallback-removal

> **Status: Stub.** This is a placeholder. Run `/plan auth-fallback-removal` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
Single backend PR. Two cleanups:
1. Delete the query-param/body fallback in `get_caller_email` / `get_caller_user_id`. Helper now hard-fails 401 if context is missing.
2. Delete the **legacy static-token shim** in the authorizer (0b). Authorizer now requires `email` + `userId` claims; tokens without them deny.
- Delete the WARN logs around fallback. Delete the INFO log for `legacy_token=true`.

## Repo
xomify-backend

## Dependencies
(1j) AND (1k) deployed AND fallback rate < 1% for 7 consecutive days (Q5)

## Exit criteria
A request with the legacy static token returns 401. A request with a per-user JWT but no context (impossible barring misconfig) returns 401. Production traffic unaffected.

## Notes
- HARD HUMAN GATE: 7-day burn-in with < 1% fallback rate before this can ship.
- Open action item from epic: product comms plan (in-app banner? release notes? force-update?) for users on stale builds before (1l) cuts them off.
- Risk: "Fallback rate never drops below threshold (stale installs)" — (1l) intentionally locks them out.
