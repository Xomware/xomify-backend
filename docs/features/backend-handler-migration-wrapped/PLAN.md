---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 1h
repo: xomify-backend
---

# backend-handler-migration-wrapped

> **Status: Stub.** This is a placeholder. Run `/plan backend-handler-migration-wrapped` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
Wrapped batch (4 handlers) — read-only, low risk.
- Each handler in the batch reads caller identity via `get_caller_email` / `get_caller_user_id` (from 0c).
- Audit each request field: caller (move to ctx) vs. target (`friendEmail`, `targetEmail`, `ownerEmail`, body `userId` for token persistence — these stay).
- Update the corresponding test file to use the `authorized_event` fixture.
- Fallback to query-param `email` is **kept** during this phase so legacy static-token clients still function.

## Repo
xomify-backend

## Dependencies
(0c)

## Exit criteria
All handlers in the batch deployed, reading from context with fallback. CloudWatch fallback WARN count > 0 expected (clients haven't migrated yet — that's what (1j)/(1k) addresses).

## Notes
- Use `backend-standards` skill.
- Read-only, low risk — flagged in epic.
- Note: only `/wrapped/*` HANDLERS migrate; `cron_wrapped` is not behind authorizer (out of scope).
