---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 1k
repo: xomify-ios
---

# ios-drop-caller-email

> **Status: Stub.** This is a placeholder. Run `/plan ios-drop-caller-email` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
Sweep iOS networking layer. Remove caller `email` from request construction. Keep target emails.

## Repo
xomify-ios

## Dependencies
ALL of (1a)–(1i) deployed AND (0d) deployed

## Exit criteria
Latest TestFlight build round-trips without caller email. Backend fallback WARN count for iOS user-agent trends to zero.

## Notes
- Requires TestFlight build + manual smoke + CloudWatch verification — human gate.
