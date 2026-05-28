---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 2b
repo: xomify-frontend
---

# music-taste-page-wire-up

> **Status: Stub.** This is a placeholder. Run `/plan music-taste-page-wire-up` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Verify path: execution agent runs `ls /Users/dom/Code/xomify-frontend/src/app/pages/` to locate the Music Taste page (likely `music-taste/` or similar).
- Add `getUserTopItems()` to `UserService` (or a new `TopItemsService` if it warrants its own file).
- Wire the Music Taste page to call this method instead of whatever it currently uses (snapshot or none).
- Loading + error states handled per existing service patterns.

## Repo
xomify-frontend

## Dependencies
(2a-infra) AND (0e)

## Exit criteria
Music Taste page shows top items refreshed within the last UTC day.

## Notes
- Open action item from epic: path to Angular Music Taste page — `ls /Users/dom/Code/xomify-frontend/src/app/pages/` at execution.
- Risk flagged: "Music Taste page (web) doesn't exist where assumed" — `ls` first; adjust the sub-feature stub if layout differs.
- Requires deploy + manual browser verification — human gate.
