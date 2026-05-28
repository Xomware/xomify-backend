# Plan: Auth Identity Hardening + Live `/user/top-items` (Epic)

**Status**: Ready
**Created**: 2026-04-26
**Last updated**: 2026-04-26 (revised — Revision 2: infra + module scope added; flipped to Ready)
**Owner**: Dominick
**Type**: Epic (orchestrate into sub-feature stubs next)
**Affected repos**:
- `/Users/dom/Code/xomify-backend` (Python lambdas)
- `/Users/dom/Code/xomify-frontend` (Angular)
- `/Users/dom/Code/xomify-ios` (Swift/SwiftUI)
- `/Users/dom/Code/xomify-infrastructure` (Terraform — API Gateway, lambdas, DDB, IAM, ACM, custom domain)
- `api-gateway-service` (external Terraform module at `git::https://github.com/domgiordano/api-gateway-service.git?ref=v2.2.0`, **NOT cloned locally** — user owns)

---

## Plan Revision Log

### 2026-04-26 — Revision 2: infra + shared-module scope added

**Why**: Revision 1 scoped the epic to 3 application repos and treated infrastructure as a single action item ("confirm where API GW routes are configured"). Investigation of `/Users/dom/Code/xomify-infrastructure/terraform/` showed that's a meaningful undercount:

- `xomify-infrastructure` (Terraform) owns the API Gateway, every lambda resource, every DDB table, IAM, the custom domain, and ACM. Every backend lambda in this epic needs a corresponding TF resource. The Track 2 cache table is provisioned here. Routes for `/auth/login` and `/user/top-items` are defined here. The authorizer redeploy happens here.
- The API Gateway itself is built from a **shared external Terraform module** (`api-gateway-service`, pinned at `v2.2.0`). Inside the module (verified at `/Users/dom/Code/xomify-infrastructure/terraform/.terraform/modules/api/endpoints.tf:28`), `var.authorization` is applied uniformly to every endpoint — there is **no per-endpoint override**. The `/auth/login` route MUST be public, so the module needs a per-endpoint `authorization` override added in a new release.

**Decision**: User chose the **module-bump path** (cleanest end state, useful for any future public route — health checks, webhooks, OAuth callbacks). The alternative (defining `/auth/login` outside the module directly in `xomify-infrastructure`) was rejected as a workaround.

**What was kept**: All goals, non-goals, the architecture diagrams, the cache TTL decision, the rollout/rollback structure, the test strategy, the migration burn-in criteria, and Revision 1's Track 0 introduction.

**What changed**:
- Affected-repos count: 3 → 5.
- Q6 answered (was action item) — module-bump path chosen.
- 4 new sub-features added: (0-pre), (0a-infra), (0b-infra), (2a-infra).
- 3 existing sub-features rescoped: (0a), (0b), (2a) now scoped to backend code only; their infra work moves to the new `-infra` siblings.
- Sub-feature total: 17 → **20**.
- Sequencing diagram updated for the new prerequisite chain.
- Risks table gains a "module bump regression" row.
- Rollout step 1 rewritten; rollback note added for (0-pre).
- Action items reorganized — Revision 1 items resolved, new items added for module release process and authorizer deploy mechanism.
- Skills section gains `infra-specialist` agent.

### 2026-04-26 — Revision 1: added Track 0 (per-user JWT issuance)

**Why**: The original plan assumed each user already authenticates with their own JWT and that the authorizer simply needed to start surfacing claims into context. Investigation showed this is false:

- iOS reads a single `XOMIFY_API_TOKEN` from `secrets.xcconfig` (`Config.swift:23`, `AuthService.swift:55`) — same token baked into every install.
- Web reads `environment.apiAuthToken` from the Angular environment file — same token in every browser.
- The authorizer (`lambdas/authorizer/handler.py:42`) verifies the JWT signature but never reads the payload. There is no per-user identity in the token at all.

So the email-as-query-param pattern that Track 1 was going to retire isn't laziness — it's the only way the backend currently knows who is calling. Removing it without first issuing per-user JWTs would lock everyone out.

**Decision**: User chose option A from a 3-way fork — build the per-user auth foundation first (Track 0), then migrate handlers to read identity from context (Track 1, unchanged in spirit), then ship the new endpoint (Track 2, unchanged in design).

**What was kept from the original plan**:
- All goals, non-goals, the Track 2 endpoint design, the cache TTL decision, the rollout/rollback structure, the risk table, the test strategy, and the sub-feature template.

**What changed**:
- Added Track 0 (per-user JWT issuance) as a hard prerequisite for Track 1.
- Track 1 sub-features now read identity from a `requestContext.authorizer` populated by real per-user JWTs (not the static shared token).
- Track 1 cleanup sub-feature (`auth-fallback-removal`) now also removes the **legacy static-token shim** in the authorizer, not just the query-param fallback in handlers.
- Added (2b) Music Taste page wire-up on web in addition to (2c) iOS — user confirmed both pages exist.
- Added six new open questions (TTL, secret rotation, web token storage, iOS keychain group, migration success criterion, public-route exemption).

---

## Problem

Three coupled problems, fixed together because each unlocks the next.

### 0. No per-user identity exists today (Track 0 — NEW)
A single static JWT is shared across every install of every client. The authorizer accepts any valid signature and discards the payload. There is no way for the backend to know which user is calling without trusting a request-supplied `email`.

### 1. Security gap (Track 1)
Because of #0, every authorized lambda accepts the caller's `email` (and sometimes `userId`) as a query-string or body field. Any holder of the static token can read or mutate any user's data by guessing an email address. Affects all 49 authorized handlers.

### 2. Stale "current" top items on iOS (Track 2)
The iOS "Top 25 — Last 4 Weeks (Current)" page reads from `GET /wrapped/all`, which only returns frozen monthly snapshots written by `cron_wrapped` on the 1st of each month. The Angular Music Taste page has the same problem. There is no live "today" endpoint — the only live `/me/top/*` path lives inside `lambdas/common/friends_profile_helper.py:get_user_top_items()` and is reachable only via the friends-profile route.

We need a live `GET /user/top-items` endpoint. Adding it on top of the current authorizer would mean shipping a brand-new endpoint that takes caller-email as a query param — institutionalizing the security gap. So Track 0 + Track 1 land first.

---

## Goals

- Each user authenticates with their own JWT, minted from their Spotify identity, on every authorized request.
- Caller identity is sourced from the JWT, not the request, on every authorized route.
- Target identity (looking up someone else's data, e.g. `friendEmail`) remains explicit in the request.
- iOS "Last 4 Weeks (Current)" page and Angular Music Taste page show top items at most ~24h stale, with one Spotify hit per user per day.
- Zero downtime during migration; no in-flight callers (legacy static-token clients, friends/profile, wrapped/all) break mid-rollout.
- Test suite migrates with the code — fixtures stub `requestContext.authorizer` once, in `conftest.py`.

## Non-Goals

- Re-architecting auth (still custom HS256 JWT; no Cognito/Auth0).
- Per-route RBAC or scopes.
- Caching anything beyond `/user/top-items`.
- Changing `/wrapped/*` semantics — Wrapped page stays on monthly snapshots.
- Backfilling historical top-items into the cache table.
- A separate `/auth/refresh` endpoint — re-mint by calling `/auth/login` again with a fresh Spotify access token (see Q1).

---

## Architecture

### Auth flow — before
```
iOS/Web --HTTPS w/ Bearer XOMIFY_API_TOKEN--> API GW --token--> Authorizer
                                                                   |
                                            Allow / Deny only — payload discarded
                                                                   v
                                                                Handler
                                                                   |
                                                  caller email = ?queryString.email
                                                  target email = ?queryString.friendEmail
```

### Auth flow — after Track 0 + Track 1
```
[once per session]
iOS/Web --POST /auth/login { spotifyAccessToken }--> auth_login lambda
                                                          |
                                              Spotify /me --> { email, id }
                                                          |
                                              mint HS256 JWT { email, userId, iat, exp }
                                                          |
                                                          v
                                              { data: { token, expiresAt } }

[every authorized request]
iOS/Web --HTTPS w/ Bearer <per-user JWT>--> API GW --token--> Authorizer
                                                                   |
                                            Allow + context: { email, userId }
                                                                   v
                                                                Handler
                                                                   |
                                  caller email = event.requestContext.authorizer.email   (TRUSTED)
                                  target email = ?queryString.friendEmail                (UNCHANGED)
```

### Request flow — `GET /user/top-items` (Track 2)
```
iOS/Web --GET /user/top-items--> API GW --> Authorizer (Allow + ctx)
                                                  |
                                                  v
                                    user_top_items handler
                                                  |
                           caller_email = ctx.email
                                                  |
                           cached = top_items_cache.get_cached(caller_email)
                                                  |
                              hit? --> return success_response(cached)
                                                  |
                              miss --v
                           user = get_user_table_data(caller_email)
                           top  = await Spotify.get_top_items_for_api()  # 6 calls
                           top_items_cache.set_cached(caller_email, top)
                           return success_response({ ...top, meta: { failed_ranges: [...] } })
```

---

## Open Question Decisions

### Q1. JWT TTL — **Recommend: 7 days**

Reasoning:
- Spotify refresh tokens are long-lived and we already persist them. The client always has a path to a fresh Spotify access token, so re-minting a Xomify JWT is one extra round-trip on cold launch — no separate `/auth/refresh` endpoint needed.
- 7 days balances re-mint frequency (rare) against blast radius if a JWT is leaked (one week max). A leaked Spotify access token is a much bigger problem; the Xomify JWT only authorizes Xomify routes.
- iOS/web 401-retry interceptor handles the boundary transparently: any 401 triggers Spotify-token refresh -> `/auth/login` -> retry once.
- Keeps the auth surface small: no refresh-token table, no rotation.

Tradeoff: a stolen JWT is valid for up to 7 days. Mitigated by HTTPS-only transport, keychain/sessionStorage at rest, and the fact that the JWT only confers Xomify access (not Spotify).

### Q2. JWT secret rotation strategy — **Recommend: dual-secret support via `kid` claim, but defer implementation**

Reasoning:
- Today the secret is in SSM (`API_SECRET_KEY`). A rotation invalidates every in-flight JWT and forces every user through `/auth/login` again — disruptive but not catastrophic (clients have the Spotify refresh token, can re-mint).
- A proper `kid` (key id) claim + dual-secret authorizer (try current, fall back to previous) would make rotation seamless. But it adds complexity that is not needed for v1.
- **For this epic**: ship with single-secret. Document the rotation behavior (forces re-login) in the auth_login sub-feature. File a follow-up issue for `kid`-based dual-secret if rotation cadence becomes painful.

### Q3. Web token storage — **Recommend: `sessionStorage`**

Tradeoffs:
- `localStorage`: persists across tabs/sessions; XSS-vulnerable.
- `sessionStorage`: cleared on tab close; XSS-vulnerable but smaller window; user re-logs each session.
- `httpOnly cookie`: not XSS-readable; requires backend CORS work + `SameSite` config + cookie-based auth in API Gateway authorizer (today it's header-based). Significant infra change.
- **Pick `sessionStorage`** for v1: better security than `localStorage` without infra rework. Re-login on tab close is acceptable for a hobby app.
- Document the cookie option as a future improvement if user-experience complaints arise.

### Q4. iOS keychain access group — **Recommend: same group as Spotify refresh token**

Reasoning:
- Both are identity material for the same user, same app target. No reason to split.
- Keeps `AuthService.swift` storage logic single-pathed.
- If/when a share extension or widget needs the JWT, the existing keychain group is already configured.

Confirm at execution: read `AuthService.swift` keychain wrapper to verify the access group constant, then reuse it for the new JWT key.

### Q5. Migration monitoring — success criterion for shipping (1l) cleanup

**Recommend: < 1% of authorized requests using fallback for 7 consecutive days**, measured per-handler in CloudWatch via the WARN log emitted by the helper.

- 7 days covers weekly-active users who only open the app on weekends.
- 1% (not 0%) accounts for users on stale app versions who refuse to update. Cleanup PR (1l) intentionally locks them out — they must update.
- Helper logs include user-agent so we can break down fallback usage by client (web vs iOS-version).

### Q6. Public route exemption for `/auth/login` — **Recommend: bump `api-gateway-service` to v2.3.0 with per-endpoint `authorization` override**

Investigation of `/Users/dom/Code/xomify-infrastructure/terraform/` revealed:
- API Gateway is built from a shared external Terraform module: `git::github.com/domgiordano/api-gateway-service.git@v2.2.0`.
- Inside the module (`endpoints.tf:28`), `var.authorization` is set uniformly across every endpoint. There is NO per-endpoint override today.
- Three options were considered:
  - (a) Bump module to v2.3.0 with per-endpoint override.
  - (b) Define `/auth/login` outside the module directly in `xomify-infrastructure/terraform/api_gateway.tf`.
  - (c) Two-API approach (overkill).
- **Decision: (a) bump the module.** Cleanest end state. Reusable for any future public route (health checks, webhooks, OAuth callbacks). User owns the module.

Module change spec:
- Each entry in the `services.<service>.endpoints[]` list gains an optional `authorization` field that overrides `var.authorization` for that endpoint. Defaults to `var.authorization` if unset.
- Backwards-compatible: existing callers that don't set the field get current behavior.
- Tag as v2.3.0. Bump the ref in `xomify-infrastructure/terraform/api_gateway.tf:91`.

### Q7. Cache TTL boundary for `/user/top-items` — **Unchanged from original plan: midnight UTC**

(Carried forward verbatim from the original revision.)
- Spotify's `/me/top/*` is computed on a rolling daily window. Aligning our cache to UTC midnight makes support trivial: _"top items refresh once per UTC day on first request"_.
- DDB native TTL has up to 48h eviction lag, so we **gate on `cachedAt` in the handler** (`if cachedAt.date() < today_utc.date(): treat as miss`). TTL attribute = `next_midnight_utc + 7 days`, purely a janitor for inactive users.

### Q8. What lives in authorizer context — **Unchanged: `email` AND `userId`**

(Carried forward.) Now satisfied unambiguously by Track 0 — `auth_login` mints both claims, so they will always be present for non-legacy callers. The dual-mode authorizer (legacy static token allowed but no context, new per-user JWT allowed with context) handles the migration window.

---

## Sub-Feature Breakdown

Each sub-feature is independently shippable and gets its own `PLAN.md` stub via `/orchestrate`. Listed in dependency order.

### Track 0 — Per-user JWT foundation

#### (0-pre) `module-per-endpoint-auth-override`
**Scope**:
- Extend the `api-gateway-service` Terraform module so each entry in `services.<service>.endpoints[]` can opt out of (or override) the shared authorizer via an optional `authorization` field. Default behavior (when unset): use `var.authorization`, which preserves today's API.
- Backwards-compatible. Existing callers see no change.
- Tag and publish as **v2.3.0**.
- Add a module-level test (or example) that confirms a NONE-auth endpoint and a CUSTOM-auth endpoint coexist in the same API GW deploy.
**Repos**: `api-gateway-service` (external; user owns; not cloned locally — clone first at execution)
**Deps**: none. Track 0 prerequisite — ships before everything else.
**Exit**: v2.3.0 tagged. Test confirms mixed-auth endpoints in a single deploy. Bumping `xomify-infrastructure` to v2.3.0 with no per-endpoint overrides set produces a no-op `terraform plan`.

#### (0a-infra) `auth-login-route-and-lambda-resources`
**Scope**:
- Bump module ref to `v2.3.0` in `xomify-infrastructure/terraform/api_gateway.tf:91`.
- Add `auth_login` lambda Terraform resource (mirror existing patterns in `lambdas_user.tf`).
- Add `/auth/login` to the appropriate `services` block with `authorization = "NONE"`.
- Add IAM policy for the lambda to read the SSM secret (`API_SECRET_KEY`).
- Update `cloudwatch.tf` for the new lambda log group.
**Repos**: `xomify-infrastructure`
**Deps**: (0-pre) — needs v2.3.0 published.
**Exit**: `terraform plan` shows the new lambda + public route. `terraform apply` succeeds. `curl -X POST /auth/login` reaches the lambda (returns 200 once the (0a) backend code is also deployed; until then, deploys an empty/stub lambda artifact or 5xx is acceptable as long as the route is wired).

#### (0a) `auth-login-endpoint`
**Scope** (lambda code only — infra moved to (0a-infra)):
- New `lambdas/auth_login/handler.py`. Public route `POST /auth/login` (route provisioned in (0a-infra)).
- Body validated: `{ spotifyAccessToken: string }`.
- Calls Spotify `/me`, extracts `email` + `id` (Spotify user id).
- Mints HS256 JWT using existing `API_SECRET_KEY`. Claims: `{ email, userId, iat, exp }`. TTL: 7 days (Q1).
- Response: `{ data: { token, expiresAt }, error: null, meta: {} }` per backend response standard.
- Tests: happy path (mock Spotify `/me`), invalid Spotify token (401 from upstream), expired Spotify token (401 from upstream), malformed request body (400).
- `DEPLOYMENT_GUIDE.md` updated.
**Repos**: backend
**Deps**: (0a-infra)
**Exit**: `curl -X POST /auth/login -d '{"spotifyAccessToken":"<valid>"}'` returns a JWT. Token decodes to expected claims. Invalid Spotify token returns structured 401.

#### (0b) `authorizer-extract-claims`
**Scope** (lambda code only):
- Modify `lambdas/authorizer/handler.py:42`.
- Decode JWT (already done). If payload contains both `email` and `userId`: include them in policy `context`.
- If payload is missing those claims (legacy static token): allow the request, but emit nothing into context. Log INFO with `legacy_token=true` for monitoring.
- This **dual-mode** behavior is what lets old clients keep working through the migration.
- Tests: per-user JWT path (context populated), legacy static-token path (allow, no context), invalid signature (deny).
**Repos**: backend
**Deps**: (0a) deployed (so we can mint test JWTs against the real authorizer)
**Exit**: Backend code merged. Note: until (0b-infra) ships, the new artifact may not be live in AWS yet.

#### (0b-infra) `authorizer-redeploy-with-claims`
**Scope**:
- Ensure the authorizer lambda's deploy artifact in AWS reflects the new dual-mode behavior from (0b).
- Verify whether `terraform/lambda_authorizer.tf` needs a `source_code_hash` bump or whether the deploy is artifact-driven via CI in `xomify-backend` (if CI pushes the zip, this sub-feature may be a no-op Terraform PR + a manual workflow trigger).
- Confirm via CloudWatch that the live authorizer is on the new version.
**Repos**: `xomify-infrastructure` (and possibly the backend deploy workflow)
**Deps**: (0b) backend code merged.
**Exit**: CloudWatch shows authorizer log version reflecting the new code. A request bearing a per-user JWT lands at a stub handler with `requestContext.authorizer = { email, userId }`. A request with the legacy static token still passes through with no context.

#### (0c) `caller-identity-helper`
**Scope**:
- Add `get_caller_email(event)` and `get_caller_user_id(event)` to `lambdas/common/utility_helpers.py`.
- Resolution order:
  1. `event.requestContext.authorizer.email` (trusted) — log DEBUG `auth_path=context`.
  2. Fallback: `event.queryStringParameters.email` or body `email` — log WARN `auth_path=fallback user_agent=<ua>` (Q5).
  3. Neither present: raise structured 401.
- Update `tests/conftest.py`: new `authorized_event` fixture that injects `requestContext.authorizer = { email, userId }`. Old `api_gateway_event` fixture stays for legacy paths during migration.
- Helper-level unit tests cover all three resolution branches.
**Repos**: backend
**Deps**: (0b-infra) deployed (otherwise context is always empty, fallback always fires, monitoring is meaningless)
**Exit**: Helper imported and exercised in a unit test. Production deploy is a no-op until handlers start using it in Track 1.

#### (0d) `ios-per-user-jwt`
**Scope**:
- After Spotify OAuth completes (existing `AuthService.saveRefreshTokenToXomify` flow at line 247), call `POST /auth/login` with the Spotify access token.
- Store returned Xomify JWT in keychain, same access group as the Spotify refresh token (Q4).
- Replace every `XOMIFY_API_TOKEN` reference (`AuthService.swift:265`, `NetworkService.swift:202`, and any others — execution agent must `grep -r "XOMIFY_API_TOKEN" /Users/dom/Code/xomify-ios/`) with the keychain-stored JWT.
- `secrets.xcconfig` entry can stay readable but must not be sent on requests post-migration. Document in commit.
- Add 401-retry interceptor in `NetworkService`: on any 401, refresh Spotify access token (existing logic) -> call `/auth/login` -> retry the original request once. Only one retry to prevent loops.
**Repos**: ios
**Deps**: (0a) deployed
**Exit**: Fresh install completes Spotify OAuth, calls `/auth/login`, stores JWT, makes an authorized request that succeeds with the per-user JWT (verify in CloudWatch — authorizer logs `legacy_token=false`).

#### (0e) `web-per-user-jwt`
**Scope**:
- After Spotify OAuth completes, call `POST /auth/login` with the Spotify access token.
- Store JWT in `sessionStorage` (Q3) under a single key, e.g. `xomify_jwt`.
- Replace every `environment.apiAuthToken` reference. Known services using it (verify count at execution): `user.service`, `ratings.service`, `invites.service`, `share-feed.service`, `groups.service`, `friends.service`, `notifications.service`, `wrapped.service`, `release-radar.service`. Likely also `shares.service`. Centralize via an `HttpInterceptor` that reads from `sessionStorage` and attaches `Authorization: Bearer <jwt>`.
- 401-retry interceptor: on any 401, refresh Spotify access token -> call `/auth/login` -> retry original request once.
- `environment.apiAuthToken` field can stay in the file but is no longer read.
**Repos**: frontend
**Deps**: (0a) deployed
**Exit**: Fresh login flow stores a JWT in `sessionStorage`. Network tab shows `Authorization: Bearer <per-user JWT>` on every API call. Authorizer logs `legacy_token=false` for these requests.

---

### Track 1 — Caller identity migration (handlers + clients drop fallback)

#### (1a) `backend-handler-migration-friends` (7 handlers)
#### (1b) `backend-handler-migration-groups` (13)
#### (1c) `backend-handler-migration-shares` (11)
#### (1d) `backend-handler-migration-invites` (4)
#### (1e) `backend-handler-migration-ratings` (4)
#### (1f) `backend-handler-migration-notifications` (2)
#### (1g) `backend-handler-migration-release-radar` (2)
#### (1h) `backend-handler-migration-wrapped` (4) — read-only, low risk
#### (1i) `backend-handler-migration-user` (3) — `user_data`, `user_all`, `user_update` (trickiest mix of caller + target)

**Scope (each batch, identical pattern)**:
- Each handler in the batch reads caller identity via `get_caller_email` / `get_caller_user_id` (from 0c).
- Audit each request field: caller (move to ctx) vs. target (`friendEmail`, `targetEmail`, `ownerEmail`, body `userId` for token persistence — these stay).
- Update the corresponding test file to use the `authorized_event` fixture.
- Fallback to query-param `email` is **kept** during this phase so legacy static-token clients still function.
**Repos**: backend
**Deps**: (0c)
**Exit (per batch)**: All handlers in the batch deployed, reading from context with fallback. CloudWatch fallback WARN count > 0 expected (clients haven't migrated yet — that's what (1j)/(1k) addresses).

#### (1j) `frontend-drop-caller-email`
**Scope**: Sweep Angular services. Remove caller `email` query params and body fields. Keep target emails (`friendEmail`, etc.).
**Repos**: frontend
**Deps**: ALL of (1a)–(1i) deployed AND (0e) deployed (web is now sending per-user JWTs; backend now reads from context)
**Exit**: Web app round-trips every authenticated request without a caller `email`. Backend fallback WARN count for web user-agents trends to zero in CloudWatch.

#### (1k) `ios-drop-caller-email`
**Scope**: Sweep iOS networking layer. Remove caller `email` from request construction. Keep target emails.
**Repos**: ios
**Deps**: ALL of (1a)–(1i) deployed AND (0d) deployed
**Exit**: Latest TestFlight build round-trips without caller email. Backend fallback WARN count for iOS user-agent trends to zero.

#### (1l) `auth-fallback-removal`
**Scope**: Single backend PR. Two cleanups:
1. Delete the query-param/body fallback in `get_caller_email` / `get_caller_user_id`. Helper now hard-fails 401 if context is missing.
2. Delete the **legacy static-token shim** in the authorizer (0b). Authorizer now requires `email` + `userId` claims; tokens without them deny.
- Delete the WARN logs around fallback. Delete the INFO log for `legacy_token=true`.
**Repos**: backend
**Deps**: (1j) AND (1k) deployed AND fallback rate < 1% for 7 consecutive days (Q5)
**Exit**: A request with the legacy static token returns 401. A request with a per-user JWT but no context (impossible barring misconfig) returns 401. Production traffic unaffected.

---

### Track 2 — Live `/user/top-items` endpoint

#### (2a-infra) `top-items-cache-table-and-route`
**Scope**:
- In `xomify-infrastructure/terraform/dynamodb.tf` add the `TOP_ITEMS_CACHE` table — PK `email`, native TTL on `ttl` attr.
- In `xomify-infrastructure/terraform/lambdas_user.tf` add the `user_top_items` lambda resource.
- Add `/user/top-items` to the `user` service endpoints block with `authorization = "CUSTOM"` (default — explicit for clarity).
- Wire env var `TOP_ITEMS_CACHE_TABLE_NAME` into the lambda.
- IAM policy grants `GetItem` + `PutItem` on the new table.
- Update `cloudwatch.tf` for the new lambda log group.
**Repos**: `xomify-infrastructure`
**Deps**: (0-pre) — module ref bump (already shipped via (0a-infra), no re-bump needed); (2a) backend code merged.
**Exit**: `terraform apply` creates the table and route. `curl GET /user/top-items` with a valid per-user JWT returns 200.

#### (2a) `user-top-items-endpoint`
**Scope** (backend lambda code + tests only — infra moved to (2a-infra)):
- `lambdas/common/top_items_cache.py`: `get_cached(email) -> dict | None`, `set_cached(email, top_items) -> None`. `get_cached` returns None if `cachedAt.date() < today_utc.date()` (Q7).
- `lambdas/user_top_items/handler.py`: reads caller email from context (via 0c), cache-then-fetch. Per-range partial failure handled — `meta.failed_ranges` is a list of strings.
- `DEPLOYMENT_GUIDE.md` updated.
- GitHub Actions deploy matrix updated.
- Tests: `tests/test_user_top_items.py` covering cache hit, cache miss, partial Spotify failure (one range raises), TTL boundary (cachedAt yesterday-UTC = miss; cachedAt today-UTC = hit), 401 on missing context.
**Repos**: backend
**Deps**: (0c). Does NOT depend on (1*) work.
**Exit**: Lambda code merged; cache helper unit-tested. End-to-end exit (route live, table populated) gated on (2a-infra) apply.

#### (2b) `music-taste-page-wire-up` (web)
**Scope**:
- Verify path: execution agent runs `ls /Users/dom/Code/xomify-frontend/src/app/pages/` to locate the Music Taste page (likely `music-taste/` or similar).
- Add `getUserTopItems()` to `UserService` (or a new `TopItemsService` if it warrants its own file).
- Wire the Music Taste page to call this method instead of whatever it currently uses (snapshot or none).
- Loading + error states handled per existing service patterns.
**Repos**: frontend
**Deps**: (2a-infra) AND (0e)
**Exit**: Music Taste page shows top items refreshed within the last UTC day.

#### (2c) `ios-current-page-wire-up`
**Scope**:
- Point "Top 25 — Last 4 Weeks (Current)" page at `GET /user/top-items` instead of `GET /wrapped/all`.
- Wrapped page (the historical snapshot view) stays on `/wrapped/all`.
**Repos**: ios
**Deps**: (2a-infra) AND (0d)
**Exit**: iOS "Last 4 Weeks (Current)" page shows top items refreshed within the last UTC day. Wrapped page unchanged.

(Decision: 2b and 2c are kept as separate sub-features. They're independent code-wise, in different repos, and gated by different upstream Track 0 sub-features.)

---

## Sub-Feature Counts

- **Track 0**: 1 module sub (0-pre) + 2 infra subs (0a-infra, 0b-infra) + 5 backend/client subs (0a, 0b, 0c, 0d, 0e) = **8**
- **Track 1**: 12 (unchanged — 1a–1l)
- **Track 2**: 1 infra sub (2a-infra) + 3 backend/client subs (2a, 2b, 2c) = **4**
- **Total**: **20**

## Hard Sequencing Edges

```
(0-pre) module-per-endpoint-auth-override   [api-gateway-service v2.3.0 published]
   |
   +---> (0a-infra) auth-login-route-and-lambda-resources   [bumps module ref; provisions lambda + public route]
   |        |
   |        v
   |     (0a) auth-login-endpoint   [lambda code]
   |        |
   |        v
   |     (0b) authorizer-extract-claims   [lambda code, dual-mode]
   |        |
   |        v
   |     (0b-infra) authorizer-redeploy-with-claims   [ship the new authorizer artifact]
   |        |
   |        v
   |     (0c) caller-identity-helper
   |        |
   |        +---> (0d) ios-per-user-jwt          (parallel with 0e)
   |        +---> (0e) web-per-user-jwt          (parallel with 0d)
   |        |
   |        +---> (1a)..(1i) backend handler batches  (parallel with each other; parallel with 0d/0e)
   |        |        |
   |        |        +---> (1j) frontend-drop-caller-email   (needs ALL 1a-1i AND 0e)
   |        |        +---> (1k) ios-drop-caller-email        (needs ALL 1a-1i AND 0d)
   |        |                |
   |        |                +---> (1l) auth-fallback-removal   (needs 1j AND 1k AND 7-day burn-in)
   |        |
   |        +---> (2a) user-top-items-endpoint   [lambda code, parallel with all of Track 1]
   |                  |
   |                  v
   |               (2a-infra) top-items-cache-table-and-route   [DDB + route + lambda resource]
   |                  |
   |                  +---> (2b) music-taste-page-wire-up   (also needs 0e)
   |                  +---> (2c) ios-current-page-wire-up   (also needs 0d)
   |
   +---> (2a-infra) also depends on (0-pre) for the module ref  [same one-time bump; no re-publish needed]
```

Note: (0-pre) is a **one-time** module publish. Once shipped, all downstream `-infra` sub-features simply consume the published v2.3.0 — they don't re-publish anything.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Module bump (0-pre) breaks existing API GW deploys | Changes are backwards-compatible (per-endpoint `authorization` field is optional, defaults to `var.authorization`). Test by applying v2.3.0 module ref to `xomify-infrastructure` with NO per-endpoint overrides set; deploy must be a no-op. |
| `/auth/login` lambda exposed publicly invites abuse | Rate-limit at API Gateway. Lambda only mints if Spotify `/me` returns 200, so attacker needs a valid Spotify token first. Log every mint with email + IP for audit. |
| Authorizer dual-mode (0b) accidentally accepts unsigned tokens | Signature verification stays mandatory. Dual-mode only bifurcates on whether claims are present, not on whether the signature is valid. Test covers both branches. |
| Old clients break before they update to per-user JWTs | (0b) keeps legacy token allowed; (1*) handlers keep query-param fallback; (1l) doesn't ship until fallback rate < 1% for 7d (Q5). |
| Fallback rate never drops below threshold (stale installs) | (1l) intentionally locks them out — that's the point. Communicate via in-app banner + force-update prompt before shipping (1l). Track this as an action item for product comms. |
| JWT secret rotation invalidates all in-flight tokens | Documented in Q2. Single-secret v1 forces re-login on rotation; clients re-mint via Spotify refresh token automatically. |
| iOS keychain group misconfigured -> JWT not retrievable across app launches | Confirmed at (0d) execution by reading existing keychain wrapper. Add a launch-time read test in `AuthService` that logs if retrieval fails. |
| Web `sessionStorage` cleared on tab close annoys users | Documented tradeoff (Q3). Re-login is one Spotify-token round-trip, transparent to user (no new OAuth window). |
| Two clients call `/auth/login` simultaneously and store different tokens | Either token is valid for 7 days. No race condition; backend doesn't track sessions. |
| Handler migration breaks in-flight callers | Query-param fallback in (1a)–(1i) keeps everything working. WARN logs make migration progress visible. |
| Tests not migrated alongside handlers | Each handler PR in (1*) MUST include its test update. CI gate. |
| Spotify rate limits during cache stampede on first launch | Cache writes per-user; miss rate decays quickly. Per-user lock skipped for v1; revisit if pathological. |
| DDB TTL eviction lag (up to 48h) leaves stale rows readable | Handler-side gate on `cachedAt.date() < today_utc.date()`. TTL is a janitor. |
| Music Taste page (web) doesn't exist where assumed | (2b) execution starts with a `ls` to confirm. If layout differs, plan adjusts in the sub-feature stub, not here. |
| Partial-failure response shape confuses iOS deserializer | Document `meta.failed_ranges` in API contract. iOS treats `null` ranges as "show prior data / show empty state". |
| Someone runs `/execute` on (0c) before (0b-infra) is in prod | Plan status gate + sub-feature `Deps:` field. Orchestrator must check upstream `Status: Done` before queuing. |

---

## Test Strategy

**Backend**:
- New `tests/test_auth_login.py`: happy path (Spotify `/me` mocked), invalid Spotify token, malformed body. Decodes returned JWT and asserts claims.
- New `tests/test_authorizer_dual_mode.py`: per-user JWT (context populated), legacy static-token (allow, no context), invalid signature (deny).
- Update `tests/conftest.py`: new `authorized_event(email='test@example.com', user_id='spotify123')` fixture.
- Each handler test in (1a)–(1i) migrates from `email` in `queryStringParameters` to `authorized_event`.
- New `tests/test_user_top_items.py`: cache hit, cache miss, partial Spotify failure, TTL boundary (freeze time), 401 on missing context.
- `pytest` runs locally and in CI before each batch deploys.

**Frontend (Angular)**:
- New unit test for the `HttpInterceptor` from (0e): attaches Bearer header from `sessionStorage`; on 401, calls `/auth/login` and retries.
- (1j) is a deletion sweep — no new tests; run existing `ng test`.
- Manual smoke: log in, hit each major page (friends, groups, shares, ratings, profile, music taste), confirm 200s in network tab and `Authorization: Bearer <jwt>` on every call.

**iOS**:
- New unit test (if test target exists) for `NetworkService` 401-retry path.
- Manual TestFlight smoke for (0d), (1k), (2c): every screen that hits the API. Verify keychain persistence across app kill/relaunch.

**Cross-cutting**:
- After each (1*) batch deploys, check CloudWatch fallback WARN counts per domain. Non-zero expected pre-(1j)/(1k); trends to zero after.
- Before (1l) ships: 7-day CloudWatch query showing < 1% fallback rate across all 49 handlers (Q5).

---

## Rollout / Rollback

**Rollout**:
1. **Track 0 prerequisite**: ship (0-pre) first — release `api-gateway-service` v2.3.0. Then ship (0a-infra) to bump the module ref in `xomify-infrastructure` and provision the `auth_login` lambda + public route. Then ship (0a) backend code which fills in the lambda body.
2. Ship (0b) backend code, then (0b-infra) to push the new authorizer artifact. Verify both code paths in CloudWatch (per-user JWT requests have context; legacy still passes).
3. Ship (0c). No-op in prod.
4. Ship (0d) and (0e) in either order. Watch authorizer logs flip from `legacy_token=true` to `legacy_token=false` as users update.
5. **Track 1 batches.** Ship (1a)–(1i) one per day, lowest-traffic-domain-first (release_radar, notifications, invites) to highest (friends, groups, shares). Each batch: PR -> CI green -> deploy -> 1h soak -> next.
6. Once (1a)–(1i) all in prod AND (0d)/(0e) shipped: ship (1j) and (1k) in either order.
7. Monitor fallback rate daily. After 7 days at < 1%: ship (1l).
8. **Track 2 in parallel** with Track 1 batches (both depend only on (0c)). Ship (2a) backend code any time after (0c). Ship (2a-infra) to provision the table + route. Ship (2b)/(2c) once (2a-infra) is live and the relevant client (0d/0e) has shipped.

**Rollback** (per stage):
- (0-pre): pin `xomify-infrastructure` back to v2.2.0 of the module — only relevant if v2.3.0 has a regression discovered post-publish. The module sub-feature itself is in a separate repo, so no in-place rollback is needed beyond the consumer's ref bump.
- (0a-infra): `terraform apply` with the route block removed (and module ref reverted if needed). Lambda resource removed. Clients fall back to the static token path (still alive until (1l)).
- (0a): delete API GW route + lambda. Clients can't mint; they fall back to the static token in `secrets.xcconfig` / `environment.apiAuthToken` (which still works because (0b)/(1l) haven't shipped). Zero impact.
- (0b): revert authorizer to prior version. Handlers don't yet read context — no impact.
- (0b-infra): re-deploy prior authorizer artifact. Handlers continue working since they don't yet read context.
- (0c): revert helper. No callers yet — no impact.
- (0d) / (0e): revert client deploy. Backend still accepts both token types via dual-mode authorizer.
- (1a)–(1i) per batch: revert that batch's handlers. Other batches unaffected. Query-param fallback keeps reverted handlers working.
- (1j) / (1k): revert client deploy. Backend fallback handles old client.
- (1l): revert. Helper goes back to fallback mode; authorizer goes back to dual-mode. Fallback warns reappear; harmless.
- (2a-infra): `terraform destroy` on the new table + route + lambda resource. No data loss (cache is regenerable).
- (2a): revert lambda code. Route still exists but returns errors until reverted handler ships or route is destroyed via (2a-infra) rollback.
- (2b) / (2c): revert client deploy. Pages go back to prior data source.

**Migration window invariant**: from the moment (0a) ships until (1l) ships, BOTH the legacy static `XOMIFY_API_TOKEN` and per-user JWTs must be accepted. (1l) is the cutover.

---

## Out of Scope

- Migrating from custom HS256 JWT to a managed identity provider (Cognito, Auth0).
- Per-route RBAC, scopes, or audit logging beyond the (0a) mint log.
- Refresh-token rotation changes.
- A separate `/auth/refresh` endpoint (Q1: re-mint via `/auth/login`).
- `kid`-claim dual-secret rotation support (Q2: deferred).
- Caching anything other than `/user/top-items`.
- Backfilling cache for inactive users.
- Replacing query-string `friendEmail` / `targetEmail` / `ownerEmail` with anything else — these are legitimate target identifiers and stay.
- Touching `cron_wrapped` or any cron lambda — they are not behind the authorizer.
- httpOnly-cookie auth on web (Q3: deferred).
- In-app banners or force-update prompts (handled by product comms before (1l)).

---

## Skills / Agents to Use

- **`/orchestrate`** (next step): turn each sub-feature (0-pre), (0a-infra), (0a)–(0e), (0b-infra), (1a)–(1l), (2a-infra), (2a)–(2c) into its own `docs/features/<slug>/PLAN.md` stub. Pass this epic doc as context.
- **`infra-specialist` agent**: invoke for (0-pre), (0a-infra), (0b-infra), (2a-infra). All Terraform/AWS work routes through this agent per project conventions.
- **`backend-standards` skill**: invoke during (0a), (0b), (0c), (1*), (2a) handler/test work to confirm response shape, type hints, and error handling conventions.
- **`/plan` per sub-feature**: each stub gets fleshed out with concrete file lists and step-by-step before its `/execute`.
- **`/fix`**: NOT to be used here. Every sub-feature is large enough to warrant a real plan.

---

## Action Items Before `/orchestrate`

These are quick reads the orchestrator (or the user) should do before stub creation; they are not blockers for this epic doc.

Resolved in Revision 2:
- [x] API Gateway route configuration location confirmed (Terraform in `xomify-infrastructure` via shared module). Q6 answered.
- [x] iOS networking layer call sites confirmed at `Xomify-iOS/Services/NetworkService.swift` and `AuthService.swift`. (Sub-feature 0d execution will still `grep -r` for any stragglers.)
- [x] Angular service file list partially confirmed (~10 services use `environment.apiAuthToken`); execution agent will sweep the full list at (0e).

Still open:
- [ ] iOS keychain access group constant — read at (0d) execution to confirm reuse of the Spotify refresh-token group (Q4).
- [ ] Path to Angular Music Taste page — `ls /Users/dom/Code/xomify-frontend/src/app/pages/` at (2b) execution.
- [ ] Path to iOS "Top 25 — Last 4 Weeks (Current)" view — grep at (2c) execution.
- [ ] Product comms plan (in-app banner? release notes? force-update?) for users on stale builds before (1l) cuts them off (Q5 risk).
- [ ] Confirm the module-bump release process for `api-gateway-service` — tagging convention, who can publish (user owns; presumably just `git tag v2.3.0 && git push --tags`, but verify).
- [ ] Confirm authorizer deploy mechanism — does `terraform apply` push the lambda zip, or is that a separate GH Actions workflow in `xomify-backend`? Determines whether (0b-infra) is real Terraform work or a workflow trigger + verification step.
