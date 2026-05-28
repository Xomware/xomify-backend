---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0e
repo: xomify-frontend
---

# web-per-user-jwt

> **Status: Stub.** This is a placeholder. Run `/plan web-per-user-jwt` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- After Spotify OAuth completes, call `POST /auth/login` with the Spotify access token.
- Store JWT in `sessionStorage` (Q3) under a single key, e.g. `xomify_jwt`.
- Replace every `environment.apiAuthToken` reference. Known services using it (verify count at execution): `user.service`, `ratings.service`, `invites.service`, `share-feed.service`, `groups.service`, `friends.service`, `notifications.service`, `wrapped.service`, `release-radar.service`. Likely also `shares.service`. Centralize via an `HttpInterceptor` that reads from `sessionStorage` and attaches `Authorization: Bearer <jwt>`.
- 401-retry interceptor: on any 401, refresh Spotify access token -> call `/auth/login` -> retry original request once.
- `environment.apiAuthToken` field can stay in the file but is no longer read.

## Repo
xomify-frontend

## Dependencies
(0a) deployed

## Exit criteria
Fresh login flow stores a JWT in `sessionStorage`. Network tab shows `Authorization: Bearer <per-user JWT>` on every API call. Authorizer logs `legacy_token=false` for these requests.

## Notes
- Tradeoff documented (Q3): `sessionStorage` cleared on tab close; re-login is one Spotify-token round-trip, transparent to user.
- Requires deploy + manual browser verification — human gate.
