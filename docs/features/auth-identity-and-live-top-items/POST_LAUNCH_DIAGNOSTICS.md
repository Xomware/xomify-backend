# Post-Launch Diagnostics — 2026-04-27

## Issue 1: Profile UI regressions

### 1a. No profile/avatar icon in top-right corner

**Root cause:** The (1j) top-nav cleanup (commit `07d20b2`, PR #250 "feat(ui): group top-nav into dropdowns, move settings into profile tab") collapsed the flat 15-link nav into 4 leaf links + 3 grouped dropdowns and **removed the explicit `'/my-profile', label: 'My Profile'` entry** from `navLinks`. The fallback was supposed to be the logo (`<a routerLink="/my-profile" class="app-title">…banner-logo-x-rework.png…</a>`), but no avatar/profile-picture chip was ever added to the top-right corner. The current toolbar has only: logo (left), nav links/dropdowns (center), Logout button (far right desktop) / hamburger (mobile). There is no surface that uses the user's `profilePicture` from `UserService.getProfilePic()`.

**Affected files:**
- `/Users/dom/Code/xomify-frontend/src/app/components/toolbar/toolbar.component.html` (no avatar element)
- `/Users/dom/Code/xomify-frontend/src/app/components/toolbar/toolbar.component.ts` (no `profilePicture` binding; doesn't inject anything that exposes the avatar URL into the template)

**Suggested fix:** Add a right-aligned anchor to `/my-profile` that renders `<img [src]="profilePicture || 'assets/img/default-avatar.png'">` as a circular chip. Pull `profilePicture` from the existing injected `UserService` (`this.userService.getProfilePic()` — already used everywhere). Place between the nav `tabs` div and the desktop Logout button so it appears far-right on desktop and replaces/precedes the hamburger on mobile. ~10 lines of HTML + a `profilePicture` getter on the component.

---

### 1b. Profile page over-fetches Spotify `/me/top/tracks` on every visit

**Root cause:** The (2b) wire-up (commit `0b15a0b`, PR #257 "Wire Music Taste page to /user/top-items") migrated `top-songs`, `top-artists`, and `top-genres` to the new `TopItemsService.getTopItems()` (which hits `/user/top-items` and is backend-cached per UTC day). **The migration deliberately did NOT touch `my-profile.component.ts`.** That page's `loadTickerData()` (lines 276–309) still calls `songService.getTopTracks('short_term')` directly against Spotify's `https://api.spotify.com/v1/me/top/tracks?limit=50&time_range=short_term`, then writes back via `setTopTracks(items, [], [])`.

Two compounding problems:
1. **In-memory cache is the only gate.** The check at line 280 (`cachedSongs.length > 0 && cachedArtists.length > 0`) is a singleton in-memory cache — survives Angular navigation but evaporates on hard reload. Since the user reports "every render," they're likely doing tab/page reloads or the cache is being clobbered.
2. **Cache poisoning.** Line 300 writes `setTopTracks(data.songs.items, [], [])` — overwriting medium/long with empty arrays. After visiting `/my-profile` first, the next visit to `/top-songs` sees `cachedMedium.length === 0` → cache miss → fires `/user/top-items`. Asymmetric caching = double fetches across the two pages. (User likely also sees this as "tracks call every time" depending on which Network tab line they were watching.)
3. **`loadAdditionalData()` always re-fires** Spotify `/me/playlists?limit=1` and `/me/following?type=artist&limit=1` on every `ngOnInit()` (no cache check at all, lines 230–252). These run before `loadTickerData()` and may also be what the user is seeing in the Network tab.

**Affected files:**
- `/Users/dom/Code/xomify-frontend/src/app/pages/my-profile/my-profile.component.ts` (lines 230–252 `loadAdditionalData`, 276–309 `loadTickerData`, 300 cache poisoning)
- `/Users/dom/Code/xomify-frontend/src/app/services/song.service.ts` (line 70 `getTopTracks` direct Spotify call)
- `/Users/dom/Code/xomify-frontend/src/app/services/top-items.service.ts` (the service that *should* be used)

**Suggested fix:** Migrate `my-profile.component.ts:loadTickerData()` to use `TopItemsService.getTopItems()` — same pattern as `top-songs.component.ts:115`. Pull `tracks.short_term`, `artists.short_term`, derive genres via `extractTopGenres`. Fix line 300 by writing `setTopTracks(short, medium, long)` from the response so the cache is fully populated and the top-songs/top-artists pages can hit the cache instead of refetching. ~15 line swap. Bonus: gate `loadAdditionalData()` behind a `playlistCount > 0 && followingCount > 0` cache check so the Spotify `/me/playlists` and `/me/following` calls don't re-fire on every navigation.

---

## Issue 2: `/likes/push` 403 ForbiddenException

**Root cause:** Most likely the **shared regional WAF ACL associated with the API Gateway stage** is blocking the request body. The route exists, the lambda exists, the deployment refreshed, and the authorizer is unrelated.

Confirmed via terraform module:
- `/Users/dom/Code/xomify-infrastructure/terraform/lambdas_likes.tf` declares `name="push"`, `path_part="push"`, `http_method="POST"` → route `/likes/push` exists.
- `/Users/dom/Code/xomify-infrastructure/terraform/api_gateway.tf:149` registers the `likes` service with the api-gateway-service module.
- The deployment trigger is `triggers.redeployment = sha1(jsonencode([timestamp()]))` (in `.terraform/modules/api/api_gateway.tf:42`) — `timestamp()` is evaluated every plan, so deployment **always** redeploys. Last terraform apply: `2026-04-27T01:54:25Z` (success, run 24972898237). Lambda code deployed at `2026-04-27T03:25:50Z` (success, run for PR #170).
- Lambda permission `aws_lambda_permission.invoke` is created per-endpoint with `source_arn = "${execution_arn}/*/*"` — wildcards over methods + resources, so it allows API GW → lambda invoke for the new route.
- Authorizer is shared with all other routes (which work). If the authorizer were the cause, **every** route would 403. Only `/likes/push` does.

**Why WAF is the prime suspect:**
- `/Users/dom/Code/xomify-infrastructure/terraform/waf.tf:15` associates a shared WAF ACL (`/xomware/shared/regional-waf-acl-arn` from SSM) with `module.api.stage_arn`. The ACL is **defined outside this repo** (in `xomware-infrastructure`) so we can't read its rules locally.
- `/likes/push` is the only POST endpoint that ships a *large* JSON body in a single hop: `LikesService.pushUserLikes()` (`xomify-frontend/src/app/services/likes.service.ts:51-65`) batches up to **100 tracks per request**, each with `trackName`, `artistName`, `albumName`, `albumArtUrl`, `trackUri`, `trackId`, `addedAt`. Realistic payload size: ~10–15 KB. **AWS WAF Managed Rules' default body inspection limit is 8 KB for the regional API Gateway.** A `SizeRestrictions_BODY` rule (part of `AWSManagedRulesCommonRuleSet`) will return 403 with `x-amzn-errortype: ForbiddenException` for any body > 8 KB.
- This perfectly matches the observed symptom: 403 ForbiddenException, no lambda invocation in CloudWatch.

**Other possibilities (lower probability, worth ruling out):**
- WAF rate-limit rule fired (the cold-open coordinator hits this once per 24h per session, so unlikely unless the user is testing repeatedly).
- WAF `BadInputs` or `SQLi` rule false-positive on the JSON body (unlikely with plain track metadata).
- The custom domain (if used) routes via CloudFront which has its own WAF — but the user's URL is the raw `wkuh988iah.execute-api...` direct stage URL, so only the regional WAF applies.

**Affected files / Terraform state:**
- `/Users/dom/Code/xomify-infrastructure/terraform/waf.tf` (the association)
- `xomware-infrastructure` repo: `/xomware/shared/regional-waf-acl-arn` SSM parameter — the actual ACL rules live there
- `/Users/dom/Code/xomify-frontend/src/app/services/likes.service.ts:37` (`BATCH_SIZE = 100` — easy lever)
- `/Users/dom/Code/xomify-frontend/src/app/services/likes-push-coordinator.service.ts:65-92` (the upstream batcher)

**Suggested fix:**
1. **Verify the cause first.** Check CloudWatch for the API Gateway stage's WAF metric — if `BlockedRequests` for the request matches the timestamp, WAF is confirmed.
2. **If WAF body-size:** Lower `BATCH_SIZE` in `likes.service.ts` from `100` to `25` (puts payload comfortably under 4 KB). One-line change. Trade-off: 4× more requests for users with > 100 likes — acceptable for a cold-open background sync.
3. **If WAF rate-limit:** Add a per-IP exemption in the shared WAF ACL for `/likes/push`, or move the WAF associations to per-route opt-in.

---

## Issue 3: iOS feed cannot delete post

**Root cause:** **HTTP method mismatch.** The iOS client POSTs to `/shares/delete`; the API Gateway route only accepts DELETE.

Confirmed:
- `/Users/dom/Code/xomify-ios/Xomify-iOS/Services/XomifyService.swift:181` — `try await network.xomifyPost("/shares/delete", body: [...])`.
- `/Users/dom/Code/xomify-infrastructure/terraform/lambdas_shares.tf:22-26` — the `delete` entry has `http_method = "DELETE"`.
- API Gateway returns `403 ForbiddenException "Missing Authentication Token"` (the standard response) when a route exists at the URL path but the requested HTTP method has no integration.
- Cross-check: the sibling `/shares/comments-delete` route is also `DELETE` in TF, and iOS calls it correctly via `xomifyDelete("/shares/comments-delete", ...)` (`XomifyService.swift` ~line 320). So the convention in iOS is "use `xomifyDelete` for DELETE routes" — `deleteShare` just never followed it.

**This bug is pre-existing — NOT caused by (1k) PR #100.** Tracing `git log -S "deleteShare" -- Xomify-iOS/Services/XomifyService.swift`, the function was originally added by commit `4e3cd20` ("refactor(ios): align Share model with deployed shares_create/shares_feed") already as `xomifyPost`. The (1k) sweep (commit `a900925`) only removed the `email` field from the body — it did not change the HTTP verb. The user attributes it to (1k) because that's when they retested feed delete; it has actually been broken since the route was first added.

**Why backend (1c) shares-handler-migration is innocent:** `lambdas/shares_delete/handler.py:51-83` correctly reads `shareId` from body OR query (line 35–48 `_extract_share_id`) and `email` from authorizer context with body fallback (line 56 `get_caller_email`). The handler would happily process the iOS payload — but it's never invoked because API Gateway rejects the POST before routing.

**Affected files:**
- `/Users/dom/Code/xomify-ios/Xomify-iOS/Services/XomifyService.swift:176-186` (the `deleteShare` function — uses `xomifyPost`)
- `/Users/dom/Code/xomify-ios/Xomify-iOS/ViewModels/Feed/FeedViewModel.swift:445-463` (calls it; works correctly once the service is fixed)
- `/Users/dom/Code/xomify-ios/Xomify-iOS/ViewModels/SharesByUserViewModel.swift:83-95` (also calls `xomifyService.deleteShare` — same wire fix unblocks both call sites)
- `/Users/dom/Code/xomify-infrastructure/terraform/lambdas_shares.tf:22-26` (route definition — keep DELETE; no infra change needed)

**Suggested fix:** In `XomifyService.swift:181`, change `network.xomifyPost("/shares/delete", body: [...])` to `network.xomifyDelete("/shares/delete", body: [...])`. The `xomifyDelete<T>(_ endpoint: String, body: [String: Any])` overload already exists (`NetworkService.swift:270`). One-line change. No backend or terraform change required.

---

## Cross-cutting observations

- **(2b) wire-up was incomplete.** The PR #257 commit message says "wires the three Music Taste pages" — it did not promise to migrate `my-profile`, but the profile page's ticker is conceptually a fourth Music Taste surface and should have been included. Suggest filing a follow-up to migrate the profile ticker for consistency and to stop poisoning the songService cache.
- **iOS HTTP-method discipline is fragile.** Three of the share routes (`delete`, `comments-delete`, `reactions-toggle`) span all three verbs (DELETE, DELETE, POST). Suggest a quick lint or compile-time check (e.g., a typed enum of route → method) so a route + method mismatch fails at build time instead of silently 403'ing in production.
- **WAF behavior is invisible from the app repos.** The likes_push 403 is not diagnosable from xomify-backend or xomify-infrastructure alone — it needs CloudWatch + the xomware-infrastructure repo. Consider exporting the WAF ACL ID into this repo's outputs so the rule list is greppable.
