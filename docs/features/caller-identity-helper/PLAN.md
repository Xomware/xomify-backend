---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0c
repo: xomify-backend
---

# caller-identity-helper

> **Status: Stub.** This is a placeholder. Run `/plan caller-identity-helper` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Add `get_caller_email(event)` and `get_caller_user_id(event)` to `lambdas/common/utility_helpers.py`.
- Resolution order:
  1. `event.requestContext.authorizer.email` (trusted) — log DEBUG `auth_path=context`.
  2. Fallback: `event.queryStringParameters.email` or body `email` — log WARN `auth_path=fallback user_agent=<ua>` (Q5).
  3. Neither present: raise structured 401.
- Update `tests/conftest.py`: new `authorized_event` fixture that injects `requestContext.authorizer = { email, userId }`. Old `api_gateway_event` fixture stays for legacy paths during migration.
- Helper-level unit tests cover all three resolution branches.

## Repo
xomify-backend

## Dependencies
(0b-infra) deployed (otherwise context is always empty, fallback always fires, monitoring is meaningless)

## Exit criteria
Helper imported and exercised in a unit test. Production deploy is a no-op until handlers start using it in Track 1.

## Notes
- Risk flagged: "Someone runs `/execute` on (0c) before (0b-infra) is in prod" — orchestrator must check upstream `Status: Done` before queuing.
