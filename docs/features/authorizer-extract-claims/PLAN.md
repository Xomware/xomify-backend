---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0b
repo: xomify-backend
---

# authorizer-extract-claims

> **Status: Stub.** This is a placeholder. Run `/plan authorizer-extract-claims` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Modify `lambdas/authorizer/handler.py:42`.
- Decode JWT (already done). If payload contains both `email` and `userId`: include them in policy `context`.
- If payload is missing those claims (legacy static token): allow the request, but emit nothing into context. Log INFO with `legacy_token=true` for monitoring.
- This **dual-mode** behavior is what lets old clients keep working through the migration.
- Tests: per-user JWT path (context populated), legacy static-token path (allow, no context), invalid signature (deny).

## Repo
xomify-backend

## Dependencies
(0a) deployed (so we can mint test JWTs against the real authorizer)

## Exit criteria
Backend code merged. Note: until (0b-infra) ships, the new artifact may not be live in AWS yet.

## Notes
- Risk flagged in epic: "Authorizer dual-mode (0b) accidentally accepts unsigned tokens" — signature verification stays mandatory; dual-mode only bifurcates on whether claims are present.
