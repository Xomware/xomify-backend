# Friend Profile + Music Match + Recent Activity — 2026-04-27

Diagnostic report for six related web/iOS issues on the friend-profile flow.
No fixes applied; this is a hand-off doc for specialist agents.

Repo paths used throughout:
- Web:     `/Users/dom/Code/xomify-frontend`
- iOS:     `/Users/dom/Code/xomify-ios`
- Backend: `/Users/dom/Code/xomify-backend`

---

## Issue 1: Friend likes don't load

**Files:**
- `/Users/dom/Code/xomify-frontend/src/app/pages/friend-profile/friend-profile.component.ts:346-348` — `goToLikes()` navigates to `/likes/<friendEmail>`.
- `/Users/dom/Code/xomify-frontend/src/app/pages/friend-profile/friend-profile.component.html:82-90` — Likes chip is the entry point and **only renders if `profile.likesCount != null`**.
- `/Users/dom/Code/xomify-frontend/src/app/pages/likes/likes.component.ts` — works correctly; routes through `/likes/:email`, hits `LikesService.getLikesByUser` for non-self path.
- `/Users/dom/Code/xomify-backend/lambdas/friends_profile/handler.py:112-122` — likesCount is **only added to payload** when the lookup succeeds AND (`is_self` OR `likes_public == True`).
- `/Users/dom/Code/xomify-backend/lambdas/likes_by_user/handler.py:108-130` — also enforces `likes_public` for non-self callers (returns 403).

**Root cause:** The Likes chip is conditionally rendered on `*ngIf="profile.likesCount != null"`. The backend `friends_profile` handler **omits** `likesCount` from the response whenever the friend has `likes_public=false`. So if the friend has hidden their likes (the default for many users post-migration), the chip disappears entirely — there is no fallback UI, no "private" state, no greyed chip. From the user's POV, "Likes does nothing."

Two sub-cases the user is conflating:
1. **Friend has `likes_public=false`**: chip is hidden by `*ngIf`. No way to navigate. Even if you craft `/likes/<friendEmail>` by hand, `likes_by_user` returns 403, and `likes.component.ts:163-167` flips `isPrivate = true` (the page DOES render a private-state, but the user never gets there).
2. **Friend has `likes_public=true` but the lookup returned a stale cached `friends_profile` response from before they enabled it**: `friends.service.ts:282-298` caches `getFriendProfile` for 10 minutes (`PROFILE_CACHE_TTL`). So the chip can lag behind the truth.

Note: there's no third case — when `likes_public=true` and the chip renders, navigation works; the likes page handles loading and the response.

**Suggested fix:**
- **Web (preferred):** Always render the Likes chip when the user is a friend. If `profile.likesCount == null`, render a chip labeled "Private" or with a lock glyph and disable the click. Mirrors iOS `ProfileHeaderView.swift:132-142` which also auto-hides — this is consistent across platforms but the user wants more explicit signaling on web.
- **Alternative backend:** Have `friends_profile` always include `likesPublic: bool` in the payload (not just `likesCount`). Web could then render `Private` vs the count without changing chip-presence logic. Cleaner contract.
- **Cache invalidation:** When a user toggles `likes_public` (from `my-profile`), broadcast an event so other clients' cached `friends_profile` entries get evicted on next visit. Lower priority — only matters for users who toggle frequently.

---

## Issue 2: Friend playlists don't load

**Files:**
- `/Users/dom/Code/xomify-frontend/src/app/pages/friend-profile/friend-profile.component.html:550-592` — Playlists tab template.
- `/Users/dom/Code/xomify-frontend/src/app/pages/friend-profile/friend-profile.component.ts:128-189` (`loadFriendStats`) and `:263-266` (`getPlaylists`).
- `/Users/dom/Code/xomify-backend/lambdas/common/friends_profile_helper.py:41-100` (`get_user_public_playlists`).
- `/Users/dom/Code/xomify-frontend/src/app/services/user.service.ts:187-194` (`getUserPublicPlaylists` → Spotify direct).
- iOS reference: `/Users/dom/Code/xomify-ios/Xomify-iOS/ViewModels/UserProfileViewModel.swift:146-171` (`parsePreloadedPlaylists`).

**Root cause:** Field-shape mismatch. The backend returns playlists in a **slim shape** (`get_user_public_playlists` line 84-92):

```
{ id, name, description, imageUrl, trackCount, uri, externalUrl }
```

The web template at `friend-profile.component.html:561` reads `playlist.images?.[0]?.url` and at line 568 reads `playlist.tracks?.total` — both **Spotify-API shapes**. The slim payload has `imageUrl` (string) and `trackCount` (int). Result: every playlist card renders with a broken/placeholder image and "0 tracks", regardless of how many backend rows came back. To the user, the tab "doesn't load".

Secondary mess: `loadFriendStats` (lines 145-167) re-fetches playlists from Spotify directly via `getUserPublicPlaylists(userId, 50)` — this returns Spotify-shaped objects (`images[0].url`, `tracks.total`) that DO match the template. Then lines 163-166 do:

```ts
if ((!this.profile.playlists || this.profile.playlists.length === 0) && data.playlists?.items) {
  this.profile.playlists = data.playlists.items;
}
```

So the Spotify-shaped fetch is only used as a fallback when the backend returned **nothing**. As long as the backend returns ANY playlists (slim shape), the fallback never runs and the user sees broken cards.

iOS handles this correctly: `parsePreloadedPlaylists` explicitly maps the slim payload into `SpotifyPlaylist` (lines 152-169 of `UserProfileViewModel.swift`).

**Suggested fix:**
- Update `getPlaylists()` (or the template) to read the slim shape: use `playlist.imageUrl || playlist.images?.[0]?.url` and `playlist.trackCount ?? playlist.tracks?.total`. This handles both shapes in case there's any drift.
- OR: Add a normalization step in `friends.service.ts:getFriendProfile` that converts slim → Spotify-ish before the component sees it. Cleaner long-term — single source of truth for shape.
- **Stop the redundant Spotify fetch** at line 147. The backend already returns the public playlists; calling Spotify again is wasteful and only exists to work around the shape bug.

---

## Issue 3: Friends-of-friends missing

**Status:** Backend issue Xomware/xomify-backend#173 is **OPEN** as of 2026-04-27. Confirmed via `gh issue view 173`.

**Files:**
- `/Users/dom/Code/xomify-frontend/src/app/pages/friend-profile/friend-profile.component.ts:151` — `this.friendsService.getFriendsList(this.friendEmail)` — passing friend's email.
- `/Users/dom/Code/xomify-frontend/src/app/services/friends.service.ts:188-217` — `getFriendsList`. Per the comments at lines 184-187, the `email` argument is now ONLY used as a cache-partition key; it is **not forwarded to the backend**. The backend reads caller from JWT context.
- `/Users/dom/Code/xomify-backend/lambdas/friends_profile/handler.py:98-122` — payload does **not** include `friendsCount`.
- iOS reference: `/Users/dom/Code/xomify-ios/Xomify-iOS/Models/SocialModels.swift:604` declares `let friendsCount: Int?` on `FriendProfile`. iOS reads it at `UserProfileViewModel.swift:256` (`friendCount = profile.friendsCount`).

**Root cause:** Two related bugs, both flowing from issue #173 not being shipped yet.

1. **Web shows `friendsCount` of the caller, not the friend.** `friend-profile.component.ts:151` calls `getFriendsList(this.friendEmail)`. Since the email arg is no longer forwarded (Track 1a migration), the backend returns the **caller's** friends list. Then line 171 sets `this.friendsCount = data.friendsList.acceptedCount` — the caller's count, displayed under the friend's name. Silently wrong.

2. **iOS shows nil/0** for the same reason — `friendsCount` is never present in the `friends_profile` payload, so `profile.friendsCount` is always nil, so the iOS header chip shows 0.

The proposed fix in #173 (option 2) is to extend `friends_profile` to include `friendsCount: int`. Once shipped:
- iOS picks it up automatically (already wired).
- Web needs to switch from the broken `getFriendsList(friendEmail)` call to reading `profile.friendsCount` directly — and **delete** the misleading service call (lines 150-151, 169-172 in `friend-profile.component.ts`).

**Suggested fix:**
- Block on backend #173. Either author the fix yourself or hand it off.
- After backend ships: web change is small — read `profile.friendsCount` from the profile payload, drop the `getFriendsList` call from `loadFriendStats`. ~10 LOC. Follow-up: also wire up the friends-of-friends LIST view if you want it to be navigable (currently the count is display-only). That requires the new `GET /friends/list?friendEmail=` endpoint variant (option 1 from #173) — a bigger change. Recommend punting on the list view for v1; just show the accurate count.

---

## Issue 4: Music match always 0

**Files:**
- `/Users/dom/Code/xomify-frontend/src/app/pages/friend-profile/friend-profile.component.ts:531-633` (`calculateCompatibility`).
- `/Users/dom/Code/xomify-frontend/src/app/services/artist.service.ts:14-71` (cache fields default to `[]`, no auto-population).
- `/Users/dom/Code/xomify-frontend/src/app/services/song.service.ts:119-132` (same — empty caches).
- `/Users/dom/Code/xomify-frontend/src/app/pages/my-profile/my-profile.component.ts:326-358` (`loadTickerData` reads `topItemsService.getTopItems()` but **never writes** to song/artist caches).

**Root cause:** Viewer-side inputs are always empty. The compatibility calc reads:

```ts
const myArtistsShort = this.artistService.getShortTermTopArtists() || [];
const myArtistsMedium = this.artistService.getMedTermTopArtists() || [];
const myArtistsLong = this.artistService.getLongTermTopArtists() || [];
const mySongsShort = this.songService.getShortTermTopTracks() || [];
const mySongsMedium = this.songService.getMediumTermTopTracks() || [];
const mySongsLong = this.songService.getLongTermTopTracks() || [];
```

I grepped for the writers:
- `setShortTermTopArtists`/`setMedTermTopArtists`/`setLongTermTopArtists` are called from exactly **two** places: `pages/news/news.component.ts:51` and `pages/top-genres/top-genres.component.ts:78-80`.
- `setShortTermTopTracks`/`setMediumTermTopTracks`/`setLongTermTopTracks` are **never called anywhere** (zero hits). The song-cache writers are dead code.

So unless the user has previously visited `/news` or `/top-genres` in the same session before opening a friend profile, every "my" array is `[]`. Then:

```
myArtistIds = ∅, mySongIds = ∅, myGenres = ∅
sharedArtists = friendArtists.filter(a => ∅.has(a.id)) = []
sharedSongs   = []
sharedGenres  = []
```

All three `*Points` calculations multiply by 0 and saturate, so `compatibilityScore = 0`. Algorithm itself (lines 612-630) is fine; inputs are wrong.

The friend's data IS available correctly — it's loaded from `profile.topSongs`/`topArtists`/`topGenres` which the backend populates from `friends_profile_helper.get_user_top_items`. So the bug is one-sided.

**Suggested fix:**
- Have `calculateCompatibility` (or a precursor) call `topItemsService.getTopItems()` directly to fetch the **viewer's** top items, then operate on that response. This is the same source `my-profile`'s ticker uses — server-cached per UTC day, so it's cheap. Don't try to repair the dead ArtistService/SongService caches; they're not the right abstraction here.
- Move the `compatibilityCalculated = false` reset to AFTER the new fetch resolves, so the loading UI is honest.
- Consider extracting compatibility into a service (`MusicMatchService` per the user's hypothesis) so the same logic can power the Friends list (mutual-affinity sort) and any future widgets.
- **iOS:** No equivalent exists. New feature. Wait until web logic is solid, then port. Backend can stay the same (top-items is already a shared lambda).

---

## Issue 5: iOS profile parity gaps (web vs iOS)

**iOS sections** (read from `/Users/dom/Code/xomify-ios/Xomify-iOS/Views/ProfileView.swift` + `ViewModels/UserProfileViewModel.swift:98-103`):
- Header: avatar, displayName, email, **stats row** (Friends, Ratings, Posts, Likes — Likes auto-hides when nil).
- Action button: "Edit Profile" (self) / "Message" (other, disabled).
- **Tabs (self):** Posts (Shares), Ratings, Taste, Playlists, Recent.
- **Tabs (other):** Posts, Ratings, Taste, Playlists. (Recent is self-only because Spotify recently-played is JWT-scoped.)

**Web sections** (read from `/Users/dom/Code/xomify-frontend/src/app/pages/my-profile/my-profile.component.html`):
- Header: avatar, displayName, email, **stats row** (Followers, Following, Friends, Playlists, Likes).
- "Open Spotify Profile" link.
- **Tabs:** Overview, Settings.
- Overview content: "Your Listening" cards (top-songs/top-artists/top-genres deep links), "Features" cards (Wrapped, Release Radar enrollment), "Account Details" panel.
- Settings content: Account info (read-only), Notifications CTA, Privacy toggle (likes_public), Logout.
- **Profile ticker** at the bottom (rotating short-term top songs/artists/genres).

**Gaps (iOS has, web doesn't):**

| iOS Section          | Status on web |
|----------------------|---------------|
| **Posts/Shares tab** | Missing as a profile tab. Shares feed exists elsewhere (`share-feed.service.ts`) but is not surfaced on the profile page. |
| **Ratings tab**      | Missing as a profile tab. `/ratings` page exists (top-level route) but is not embedded in profile. |
| **Recent tab** (last 25 played) | Missing entirely on web profile. No equivalent component or service surfacing recently-played tracks. |
| **Taste tab** (auto-rotating top-3 per term) | Web has the bottom ticker which is similar but inferior — only short_term, no per-term browsing, no "See all" CTA. |
| **Posts/Ratings/Likes counts in header stats row** | Web header shows Followers/Following/Friends/Playlists/Likes. iOS shows Friends/Ratings/Posts/Likes. Web is missing Posts and Ratings counts. |
| **Profile-tab navigation pattern** | iOS uses tabs to keep everything on one screen. Web uses a card-grid that punts everything to separate routes. Different UX philosophy. |

**Web has (iOS doesn't):**
- Followers/Following counts in header (Spotify-direct).
- Wrapped + Release Radar enrollment cards.
- Account info panel (country, product, userId).
- Privacy toggle (`likes_public`) — iOS has this in Settings, not profile.
- Bottom rotating ticker.
- Compatibility/Music Match (only on **friend** profile — see Issue 4).

**Suggested order to ship** (smallest blast radius first):
1. **Add Recent tab** — single Spotify call (`/me/player/recently-played`), self-only. Reuse styling from existing track lists (e.g. likes page row component). Lowest risk; immediate value. Mirror iOS `ProfileRecentTab.swift` 1:1.
2. **Add Ratings count to header**. Reuse `RatingsService.getAllRatings`. One number, drop into stats row. Tap-through can stay broken (already routes to `/ratings`).
3. **Add Posts/Shares count to header.** Reuse `share-feed.service.ts`. Same pattern.
4. **Add Taste tab** (auto-rotating). Replaces the bottom ticker (delete it). Bigger refactor — touches the page layout. Worth doing for parity but should land in its own PR.
5. **Add Shares + Ratings tabs as top-level profile tabs.** This is the biggest UX shift on web — moves from card-grid → tab-grid. Recommend doing this LAST, after the smaller pieces, because it's a re-architecture of the page. May want a brainstorm session first to align the layout with iOS without breaking web's existing affordances (Wrapped/Release Radar cards still need a home).

---

## Issue 6: Following 'Recent Activity' tab

**Files:**
- `/Users/dom/Code/xomify-frontend/src/app/pages/following/following.component.ts:25` — `viewMode: 'artists' | 'activity'`.
- `/Users/dom/Code/xomify-frontend/src/app/pages/following/following.component.html:198-201` — wires `<app-activity-timeline>` inside the activity view.
- `/Users/dom/Code/xomify-frontend/src/app/components/activity-timeline/activity-timeline.component.{ts,html}` — fully implemented; declared in `shared.module.ts:9` and imported into discovery.module.
- `/Users/dom/Code/xomify-frontend/src/app/services/liked-artists-activity.service.ts:81-150` — `loadActivityTimeline()` exists and works. Iterates ALL followed artists, fetches recent releases per artist via `getArtistRecentReleases`, builds a reverse-chronological timeline.

**Today:** the tab is **wired and functional** in the codebase — it is NOT inert. When you click "Recent Activity," it mounts `<app-activity-timeline>`, which on `ngOnInit` calls `loadActivityTimeline()`. Why the user perceives it as doing nothing:

1. **First load is extremely slow.** The service fans out one Spotify `getArtistRecentReleases(artistId, 10)` call per followed artist (line 100-110). For users following 50+ artists, that's 50+ HTTPS calls in parallel before anything renders. The component has `loading = true` for the entire duration with no progressive UI. Looks frozen.
2. **No followed artists → empty timeline.** If the user follows 0 artists, the service returns `{ activities: [], stats: emptyStats }` (lines 117-122). The `activity-timeline.component.html` renders the header + filter bar + an empty list — no overt "you're not following anyone" empty state at the same level.
3. **Cache hides errors.** `getCache()` (line 83) returns cached results without re-fetching, so if the first load partially failed, the user sees stale or empty results until the cache expires.
4. **Duplicates `/release-radar` content.** The page exists already at `/release-radar` and is more polished (per `app-routing.module.ts:55`). The activity tab on `/following` is functionally a worse, slower copy.

**Options:**
- **Keep & wire:** Add progressive rendering (show artists as they resolve), surface a real loading message ("Checking 47 artists for new releases…"), add a clear empty state for the no-followed-artists case. ~half-day of work. Result: still slower and uglier than `/release-radar`.
- **Repurpose:** Replace with a friend-recent-likes timeline (e.g. "what your friends liked this week"). Different data source, more social. Reuses the timeline UI shell. Bigger product decision.
- **Remove:** Delete the activity view-mode, drop `setViewMode`, drop `viewMode === 'activity'` block, drop the `<app-activity-timeline>` reference. The timeline component itself can stay (it's unused but harmless) or be deleted along with the unused `LikedArtistsActivityService`. Lowest effort. Best UX: users still have `/release-radar` for the same need.

**Recommendation:** **Remove.** The tab is a redundant slower copy of `/release-radar`, the user perceives it as broken, and there is no unique value over the dedicated page. Add a subtle "See new releases" link from the Following page header that routes to `/release-radar` to preserve the discovery affordance. If you later want a social-flavored activity timeline, file it as its own feature so it gets a proper design.
