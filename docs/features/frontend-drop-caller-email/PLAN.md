---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 1j
repo: xomify-frontend
---

# frontend-drop-caller-email

> **Status: Stub.** This is a placeholder. Run `/plan frontend-drop-caller-email` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
Sweep Angular services. Remove caller `email` query params and body fields. Keep target emails (`friendEmail`, etc.).

## Repo
xomify-frontend

## Dependencies
ALL of (1a)–(1i) deployed AND (0e) deployed (web is now sending per-user JWTs; backend now reads from context)

## Exit criteria
Web app round-trips every authenticated request without a caller `email`. Backend fallback WARN count for web user-agents trends to zero in CloudWatch.

## Notes
- Deletion sweep — no new tests; run existing `ng test`.
- Manual smoke required: log in, hit each major page (friends, groups, shares, ratings, profile, music taste), confirm 200s in network tab.
- Requires deploy + CloudWatch verification — human gate.
