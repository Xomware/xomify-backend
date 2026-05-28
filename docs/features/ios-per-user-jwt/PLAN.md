---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0d
repo: xomify-ios
---

# ios-per-user-jwt

> **Status: Stub.** This is a placeholder. Run `/plan ios-per-user-jwt` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- After Spotify OAuth completes (existing `AuthService.saveRefreshTokenToXomify` flow at line 247), call `POST /auth/login` with the Spotify access token.
- Store returned Xomify JWT in keychain, same access group as the Spotify refresh token (Q4).
- Replace every `XOMIFY_API_TOKEN` reference (`AuthService.swift:265`, `NetworkService.swift:202`, and any others — execution agent must `grep -r "XOMIFY_API_TOKEN" /Users/dom/Code/xomify-ios/`) with the keychain-stored JWT.
- `secrets.xcconfig` entry can stay readable but must not be sent on requests post-migration. Document in commit.
- Add 401-retry interceptor in `NetworkService`: on any 401, refresh Spotify access token (existing logic) -> call `/auth/login` -> retry the original request once. Only one retry to prevent loops.

## Repo
xomify-ios

## Dependencies
(0a) deployed

## Exit criteria
Fresh install completes Spotify OAuth, calls `/auth/login`, stores JWT, makes an authorized request that succeeds with the per-user JWT (verify in CloudWatch — authorizer logs `legacy_token=false`).

## Notes
- Open action item from epic: iOS keychain access group constant — read at execution to confirm reuse of the Spotify refresh-token group (Q4).
- Requires TestFlight build + manual smoke — human gate.
