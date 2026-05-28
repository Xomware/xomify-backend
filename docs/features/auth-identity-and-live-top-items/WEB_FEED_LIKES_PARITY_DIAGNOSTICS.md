# Web Feed/Likes Parity — 2026-04-27

Diagnoses gaps between the web (Angular) and iOS (SwiftUI) feed share-cards, plus a broken `/likes` page on web. Backend endpoints are already deployed for everything iOS does, so the work is purely frontend.

References:
- Web feed page: `/Users/dom/Code/xomify-frontend/src/app/pages/feed/feed.component.{ts,html}`
- Web share card: `/Users/dom/Code/xomify-frontend/src/app/components/share-card/share-card.component.{ts,html,scss}`
- Web share-feed service: `/Users/dom/Code/xomify-frontend/src/app/services/share-feed.service.ts`
- iOS feed: `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/Feed/FeedView.swift`
- iOS share card: `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/Feed/ShareCardView.swift`
- iOS share detail: `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/Feed/ShareDetailView.swift`
- iOS share-card VM: `/Users/dom/Code/xomify-ios/Xomify-iOS/ViewModels/Feed/ShareCardViewModel.swift`
- iOS share-detail VM: `/Users/dom/Code/xomify-ios/Xomify-iOS/ViewModels/Feed/ShareDetailViewModel.swift`
- iOS friends-rated drilldown: `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/Feed/FriendsRatedListView.swift`
- iOS friends-queued drilldown: `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/Feed/FriendsQueuedListView.swift`
- iOS reactions bar: `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/Feed/ReactionsBar.swift`
- Backend `shares_detail`: `/Users/dom/Code/xomify-backend/lambdas/shares_detail/handler.py`
- Backend `likes_by_user`: `/Users/dom/Code/xomify-backend/lambdas/likes_by_user/handler.py`

---

## Issue 1: Feed share-card UI gaps

### Per-feature audit

| Feature | iOS impl | Web impl | Gap | Suggested fix file |
|---|---|---|---|---|
| Tap card body → push detail screen | `ShareCardView.swift:116-125` (Button wraps `detailTapZone`) + `FeedView.swift:124-126,145-151` (`navigationDestination(item:)`) routes to `ShareDetailView` | None. `share-card.component.html:1-170` only exposes `openAuthor()` (avatar tap → friend profile). No share-detail navigation. No `share-detail` page or route in `pages/`. | Missing entirely. There is no web `pages/share-detail/` and no router entry for it. (`pages/share/` is a "share my top stats" screenshot composer, unrelated.) | New page `pages/share-detail/` + new method `ShareFeedService.getShareDetail(shareId, sharedBy?, sharedAt?)` calling `GET /shares/detail`. Add `(click)="openDetail()"` on the card body (header + track block + caption + tags) in `share-card.component.html`. Wire route in `app-routing.module.ts`. |
| Comment thread (list + composer + delete) | `ShareDetailView.swift:385-514` (commentsSection / composer / row) backed by `ShareDetailViewModel.swift:154-229` calling `XomifyService.listComments / createComment / deleteComment`. Card surfaces a count via `commentButton` (`ShareCardView.swift:351-373`). | None. `share-feed.service.ts` has no comment methods. `share-card.component.html` has no comment button or count. `Share` interface (`share-feed.service.ts:23-45`) has no `commentCount`. | Missing entirely. | Add `commentCount?: number` to `Share` interface. Add comment button + count to `share-card.component.html` next to/below the kebab. Build comment list + composer inside the new `share-detail` page. New service methods on `ShareFeedService`: `listComments(shareId, limit?, before?)`, `createComment(shareId, body)`, `deleteComment(shareId, commentId)` hitting `GET/POST/DELETE /shares/comments-*`. |
| Reaction emoji bar (toggle 6 emojis, viewer-state pills, smiley picker) | `ReactionsBar.swift` (shared between card + detail) wired through `ShareCardViewModel.toggleReaction` (`ShareCardViewModel.swift:149-187`) calling `XomifyService.toggleReaction` → `POST /shares/reactions-toggle`. | None. The "rating" thing on the card is the 1-5 star personal rating (`viewerRating`). No emoji reactions, no reactions row, no reaction summary fields. | Missing entirely. `Share` interface has no `reactionCounts` / `viewerReactions`. | Add `reactionCounts: Record<string, number>` and `viewerReactions: string[]` to `Share`. Build a `ReactionsBarComponent` (mirror of `ReactionsBar.swift` — pills for active reactions + smiley + popover picker). New service method `toggleReaction(shareId, reaction)` calling `POST /shares/reactions-toggle`. Render bar inside `share-card.component.html` and again inside the new `share-detail` page. |
| Friends-ratings indicator + drilldown ("N friends rated, 3.8 avg") | `ShareDetailView.swift:220-235` stat tile → `FriendsRatedListView.swift` lists each friend with their stars + review. `averageFriendRating` computed in `ShareDetailViewModel.swift:104-108` from `friendRatings` returned by `/shares/detail`. Card already shows raw `ratedCount` (`Share.ratedCount`). | The card shows `ratedCount` only as `{{ ratedCount }} rated` text (`share-card.component.html:58-60`). No drilldown, no average, no list of friends. | Drilldown + average missing. The `ratedCount` integer is already on the card but unactionable. | Wire from the new `share-detail` page. `/shares/detail` already returns `friendRatings: [{email, displayName, avatar, rating, review, ratedAt}]` — render a stat tile that links to a `friends-rated` modal/sub-view. Compute `average = sum(rating) / length` client-side (same as `averageFriendRating` in `ShareDetailViewModel.swift:104-108`). |
| Friends-listens indicator + drilldown ("N friends queued") | `ShareDetailView.swift:204-218` stat tile → `FriendsQueuedListView.swift`. Sourced from `interactions` filtered to `action == "queued"` (`ShareDetailViewModel.swift:98-100`). | Card shows raw `queuedCount` on the Queue pill (`share-card.component.html:92`). No drilldown, no friend list. | Drilldown missing. Count is on the wrong control. | Same as above — render in the new `share-detail` page. `/shares/detail` returns `interactions: [{email, displayName, avatar, action, createdAt}]`; filter where `action == "queued"`. |
| Average-rating display | Implicit in friends-rated drilldown (`FriendsRatedListView` averageCard, lines 53-75). Not on the card itself. | Not present anywhere. | Same gap as friends-ratings drilldown. | Same fix. |
| Queue / mark-as-listened action | iOS deliberately removed the front-of-card Queue shortcut and folded it into the `TrackActionsMenu` (the kebab). See `ShareCardView.swift:322-324` comment: *"The `Queue` shortcut moved into the Actions menu"*. The on-detail "queued count" is read-only. | The web card has BOTH a primary `queue-btn` (`share-card.component.html:65-93`) AND a duplicate "Add to Queue" item inside the kebab menu (`share-card.component.html:130-141`). Both call `toggleQueue()` (`share-card.component.ts:115-157`) which actually writes through `POST /shares/react?action=queued`. | Duplicate, prominent on the card, not gated to author/friend. | Delete the entire `<button class="queue-btn">…</button>` block (`share-card.component.html:65-93`) and the corresponding `.queue-btn` SCSS. Keep the kebab `menuQueue()` entry — but consider whether it should call `playerService` to actually add to Spotify queue (iOS path) instead of just flipping the `viewerHasQueued` flag in DynamoDB (current web behavior). |

### Vertical 3-dot menu

The kebab SVG in `share-card.component.html:104-114` is hand-drawn with three circles stacked **vertically**:

```
<circle cx="12" cy="5"  r="1.5" />
<circle cx="12" cy="12" r="1.5" />
<circle cx="12" cy="19" r="1.5" />
```

There is no CSS rotation applied (`grep -n "rotate" share-card.component.scss` → 0 hits). It just looks weird because iOS uses `Image(systemName: "ellipsis")` which is **horizontal** (`TrackActionsMenu.swift:108,117`). Two options:

1. Swap the circle coordinates to horizontal: `cx="5"/"12"/"19"` and `cy="12"`. Lowest-risk.
2. Replace with an inline SF-Symbol-equivalent SVG (three horizontal dots).

Either is one-line. The user almost certainly wants horizontal to match iOS conventions.

### Queue button: what it does today

- **iOS**: `ShareCardViewModel.queue()` calls `SpotifyPlaybackCoordinator.queueTrack(uri:)` — actually queues on Spotify. The "queued count" surfaces only as a passive chip on the card and a stat tile on detail; there's no toggle button on the card front. The button moved into the `TrackActionsMenu` (kebab).
- **Web**: `ShareCardComponent.toggleQueue()` (`share-card.component.ts:115-157`) calls `ShareFeedService.reactToShare(email, shareId, 'queued' | 'unqueued')`, which hits `POST /shares/react`. This only flips a `viewerHasQueued` boolean in DynamoDB — **it does not actually add the track to Spotify's queue**. So the button is misleading: it looks like "play later" but it's really "mark as interested". And it's duplicated in the kebab.

**Recommendation**: drop the front-of-card Queue button entirely. Keep `Add to Queue` in the kebab and (separately, when the player parity work happens) wire it through the existing `PlayerService` to Spotify, the same way iOS does.

### Suggested order to ship (web)

1. **Quick win — kebab orientation**: rotate or replace the kebab SVG in `share-card.component.html:104-114`. Single-line diff.
2. **Quick win — kill the Queue button**: delete the `<button class="queue-btn">` block + scss. Keep the kebab item.
3. **New `share-detail` page** scaffolding:
   - Add `getShareDetail` to `ShareFeedService` → `GET /shares/detail?shareId=&sharedBy=&sharedAt=`.
   - Create `pages/share-detail/share-detail.component.{ts,html,scss}` mirroring `ShareDetailView.swift` (hero art, sharer block, stats row, action row).
   - Add a route `share/:shareId` in `app-routing.module.ts`.
   - Make the card body clickable: wrap header + track + caption + tags in a `(click)="openDetail()"`; do NOT include the action footer in that click target (mirrors `ShareCardView.swift:116-125`).
4. **Comments**:
   - Extend `Share` with `commentCount?: number` (already returned by backend, see `shares_detail/handler.py` and `shares_feed`).
   - Add `commentButton` to the card with the count.
   - Inside the share-detail page, add a `CommentThreadComponent` (composer + list + delete). New service methods: `listComments`, `createComment`, `deleteComment`.
5. **Reactions**:
   - Extend `Share` with `reactionCounts: Record<string, number>` and `viewerReactions: string[]`.
   - Build a `ReactionsBarComponent` shared between the card and detail.
   - New service method `toggleReaction(shareId, reaction)`.
6. **Friends-rated / friends-queued drilldowns**:
   - On the share-detail page, render two stat tiles. Each opens a dialog (or sub-view) listing `friendRatings` / `interactions[action=queued]` from the same `/shares/detail` response.
   - Compute average client-side; mirror `averageFriendRating` in `ShareDetailViewModel.swift:104-108`.

No new backend work. Every endpoint above is already in `lambdas/`.

---

## Issue 2: Web `/likes` performance

### Data path on iOS

`LikesView.swift:30-34` picks one of two sources at init:

- **Self path** (`targetEmail == nil`) → `LikesSource.spotifyDirect` → `LikesViewModel.fetchSpotifyPage()` (`LikesViewModel.swift:137-161`) calls `SpotifyService.getSavedTracks(limit: 50, offset:)`. Direct Spotify API. Lazy — first page is 50 tracks; `loadMore()` triggers more when the user scrolls within 5 of the end (`LikesView.swift:106-110`).
- **Friend path** (`targetEmail` set) → `LikesSource.backend` → `LikesViewModel.fetchBackendPage` (`LikesViewModel.swift:163-194`) calls `XomifyService.getLikesByUser(email:, targetEmail:, limit:, offset:)` → `GET /likes/by-user?email=&targetEmail=&limit=&offset=`.

**Key**: self likes load fast on iOS because they go straight to Spotify in a single 50-track page. The backend is bypassed entirely.

### Data path on web

The web is broken in two places.

**(a) Page-load query is malformed.** `LikesService.getLikesByUser` (`/Users/dom/Code/xomify-frontend/src/app/services/likes.service.ts:75-92`) sends:

```
GET /likes/by-user?email=<viewer>&limit=30&cursor=<token>&q=<search>
```

Backend `lambdas/likes_by_user/handler.py:88-89, 92-99` requires `targetEmail` and reads pagination from `offset` (integer), not `cursor`. It does not support `q`. Contract:

| Param | Web sends | Backend expects |
|---|---|---|
| `targetEmail` | (never) | required |
| `email` (the target) | `<viewer email>` | (used for legacy caller fallback only) |
| `cursor` | `<string>` | (ignored; backend uses `offset` int) |
| `limit` | `30` | OK |
| `q` | `<string>` | (not supported — search is iOS-side only) |

So:
- The backend will treat `email` as the caller and have no `targetEmail`, then `require_fields(params, "targetEmail")` raises `ValidationError` → 400. **The very first page request fails.** That's why "it never finishes loading" — the loader stays up until the HTTP error tab, then there are no tracks to render (and `loading=false` only after the catch).
- Even if the request succeeded, `cursor` is never read; `loadMore()` (`likes.component.ts:78-99`) reads `resp.cursor` which the backend never returns → `cursor` stays `null` → "load more" is hidden → infinite scroll feel never works.

**(b) `LikesPushCoordinator` is fired on every app boot.** `app.component.ts:46` calls `this.likesPushCoordinator.runIfDue().subscribe()` unconditionally on `ngOnInit` for any logged-in user. The coordinator stores its last-pushed timestamp in `sessionStorage` (`likes-push-coordinator.service.ts:8, 44, 55`), which is **per-tab/per-session** — so it re-runs every time you open a new tab or refresh. `runIfDue` then calls `SongService.getAllUserTracks(0)` (`song.service.ts:45-68`), which:

- Fetches `/me/tracks?limit=50&offset=0`,
- Increments `offset += 300` (a bug — should be `+= 50`),
- Recurses synchronously (`fetchTracks()` calls itself inside the `subscribe.next` callback, no break),
- Stops only when an empty page returns.

For a library of N tracks this issues `ceil(N / 300) + 1` Spotify requests, each one paginated wrong (missing 250 tracks per cycle), then immediately `pushUserLikes` chunks 25-at-a-time `POST /likes/push`. None of this blocks UI directly, but it monopolizes the Spotify rate limit and the Network tab, and the `pushUserLikes` `concatMap` keeps round-tripping for tens of seconds.

While none of (b) is in the critical render path of `/likes`, it competes for HTTP connections and creates the perception that the whole page hangs.

### Why slow

**Primary cause: the page load request is malformed.** `getLikesByUser(email)` sends `email=<viewer>` and `cursor=<token>`. Backend rejects (missing `targetEmail`), so the first `loadPage` returns an error, `loading=false`, and the page renders empty. If the backend currently isn't 400'ing in production, it's because something is supplying a default — but the cursor is still undefined in the response and pagination stalls.

**Secondary cause: `LikesPushCoordinator` runs on every new tab.** `sessionStorage` resets per session; the 24h interval check is effectively a no-op on a fresh tab. The `getAllUserTracks` paginator is also buggy (`offset += 300` with `limit=50`).

iOS doesn't suffer either: self-likes go straight to Spotify in a single 50-track lazy page; there is no push-on-boot.

### Suggested fix

Two independent fixes, one critical and one cleanup:

1. **Fix `LikesService.getLikesByUser` to match the backend contract** (`/Users/dom/Code/xomify-frontend/src/app/services/likes.service.ts:75-92`):
   - Accept and pass `targetEmail` as the param name (rename the first arg or add a second).
   - Replace `cursor: string` pagination with `offset: number`. Read `total` and `hasMore` from the response, derive `cursor`-equivalent locally as `items.length < total`.
   - Drop the `q` param — it's not server-side. Filter client-side like iOS does (`LikesViewModel.filteredItems`, `LikesViewModel.swift:61-67`).
   - Update `likes.component.ts:78-99,133-155` to use offset-based pagination.

2. **Optionally add a Spotify-direct path for self-view**, mirroring iOS `LikesSource.spotifyDirect`. This makes self-likes feel as fast as iOS even when the backend cache is cold (e.g., right after a fresh OAuth). The page already has `email` and `isSelf`; branch to `SongService.getUserTracks(offset)` when `isSelf`. Re-use the existing pagination harness.

3. **Fix `LikesPushCoordinator` cadence and pagination** (`/Users/dom/Code/xomify-frontend/src/app/services/likes-push-coordinator.service.ts`, `/Users/dom/Code/xomify-frontend/src/app/services/song.service.ts:45-68`):
   - Move the "last pushed" timestamp from `sessionStorage` to `localStorage` so the 24h gate actually persists across tabs.
   - Fix `getAllUserTracks` — `offset += 300` should be `offset += data.items.length` (or `+= 50` to match the page size).
   - Even better: schedule `runIfDue` to fire after the first user-initiated navigation (`NavigationEnd`) instead of synchronously in `ngOnInit`, so it doesn't compete with the actual page render.

Order of operations: ship #1 first (it's the cause of the visible breakage), #3 second (silently improves perceived performance), #2 last as nice-to-have parity.
