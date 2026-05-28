---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0a
repo: xomify-backend
---

# auth-login-endpoint

> **Status: Stub.** This is a placeholder. Run `/plan auth-login-endpoint` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- New `lambdas/auth_login/handler.py`. Public route `POST /auth/login` (route provisioned in (0a-infra)).
- Body validated: `{ spotifyAccessToken: string }`.
- Calls Spotify `/me`, extracts `email` + `id` (Spotify user id).
- Mints HS256 JWT using existing `API_SECRET_KEY`. Claims: `{ email, userId, iat, exp }`. TTL: 7 days (Q1).
- Response: `{ data: { token, expiresAt }, error: null, meta: {} }` per backend response standard.
- Tests: happy path (mock Spotify `/me`), invalid Spotify token (401 from upstream), expired Spotify token (401 from upstream), malformed request body (400).
- `DEPLOYMENT_GUIDE.md` updated.

## Repo
xomify-backend

## Dependencies
(0a-infra)

## Exit criteria
`curl -X POST /auth/login -d '{"spotifyAccessToken":"<valid>"}'` returns a JWT. Token decodes to expected claims. Invalid Spotify token returns structured 401.

## Notes
- Use `backend-standards` skill for response shape, type hints, and error handling conventions.
- End-to-end exit verification depends on (0a-infra) being applied to AWS.
