# Backend Contract — iOS Profile Redesign (Phase 0)

**Status**: Ready for review
**Created**: 2026-04-23
**Consumer**: xomify-ios `docs/features/ios-profile-redesign/PLAN.md`
**Owner (iOS side)**: Dom

This doc answers the four backend asks in the iOS profile-redesign plan's
"Backend Dependencies" section. Two of the four are already live; two need
small server-side changes before iOS Phase 0 can close.

---

## 1. `GET /shares/user` — live, no changes

**Handler**: `lambdas/shares_user/handler.py`

### Query params
| Name | Required | Notes |
|------|----------|-------|
| `email` | yes | the **requester** (viewer). Kept for future friendship gating + enrichment. |
| `targetEmail` | yes | the **author** whose shares we're listing. |
| `limit` | no | default `50`, max `100`. Integer. Returns `400` on bad input. |
| `before` | no | ISO8601 `createdAt` cursor — items strictly older than this. |

### Response
```json
{
  "shares": [ /* Share objects, newest first, same shape as /shares/feed */ ],
  "nextBefore": "2026-04-20T14:05:22Z"   // null when no more pages
}
```
Each share is enriched with `queuedCount`, `ratedCount`, `viewerHasQueued`,
`viewerRating`, `sharerRating` — identical to the feed contract.

### Auth
Currently **no friendship gate**. Any authenticated caller can list any
user's shares. Comment in the handler flags this as "v1" — if product
wants friend-only visibility later, gate inside the handler using
`list_all_friends_for_user(email)` (same pattern as `shares_feed`) and
return `403` with a structured error for non-friends.

### iOS-side corrections to the plan
Two divergences between the plan's assumed contract and the actual one:
- **Query param** is `targetEmail`, not `email`. The iOS plan's line 56
  says `getSharesByUser(email:before:limit:)` — the Swift signature is
  fine, but the URL builder needs to send both `email` (caller) and
  `targetEmail` (target).
- **Cursor field** is `nextBefore`, not `nextCursor`. Update
  `SharesByUserResponse` accordingly.

---

## 2. `GET /ratings/all?email=<any>` — live, not caller-gated

**Handler**: `lambdas/ratings_all/handler.py`

Takes a single `email` query param and returns **that** user's ratings.
No comparison between caller and target. iOS Phase 4 for `.other` works
without backend changes.

### Response (unchanged)
```json
{
  "ratings": [ /* TrackRating objects */ ],
  "totalRatings": 42
}
```

### Future consideration (not blocking)
If we ever want private ratings, gate inside the handler the same way
`shares_feed` gates with `list_all_friends_for_user`. No current plan to
do this.

---

## 3. `GET /friends/profile` — needs two small changes

**Handler**: `lambdas/friends_profile/handler.py`

### Current response
```json
{
  "displayName": "...",
  "email": "...",
  "userId": "...",
  "avatar": "...",
  "topSongs":   { "short_term": [...], "medium_term": [...], "long_term": [...] },
  "topArtists": { "short_term": [...], "medium_term": [...], "long_term": [...] },
  "topGenres":  { "short_term": [...], "medium_term": [...], "long_term": [...] }
}
```

### Already present (iOS plan got the gap wrong)
- **All three term buckets** for tracks / artists / genres — the response
  already returns `short_term` / `medium_term` / `long_term` dicts. iOS
  Phase 5 taste-tab fallback ("if only one term bucket is populated,
  hide the picker") is a no-op — we always return three. The fallback
  should instead check for **empty arrays** per bucket (target user
  without enough listening history in a window returns `[]`).
- **Album art for top tracks/artists** — the `topSongs` / `topArtists`
  payloads are the raw Spotify track/artist objects, which include
  `album.images[].url` and `images[].url` respectively. iOS doesn't
  need text-only tiles; it needs a decoder that reads the same shape
  as `SpotifyService.getTopItems` already does for `.me`.

### Changes needed
**3a. Add `shareCount: Int` to the response.** *(blocker for iOS Phase 2 header parity)*
- Source: count of share records where `email == friendEmail`.
- Cheapest implementation: query the `email-createdAt-index` GSI on the
  Shares table with `Select=COUNT` (no items returned, billed per kb
  scanned — a few cents per million requests at profile scrape rates).
  Same GSI `list_shares_for_user` already uses.
- Fallback if count scan is too costly: denormalize a `shareCount`
  counter on the Users record and increment/decrement on
  `shares_create` / `shares_delete`. Don't start here — add only if the
  GSI scan shows up in billing.

**3b. Known performance caveat — not blocking, flagged for awareness.**
The handler currently spins up a live Spotify session for the target
user on every request (`get_user_top_items` → Spotify `/me/top/tracks`
and `/me/top/artists`, 3 time-range calls each, in parallel). That's
~6 Spotify API calls per profile load, plus the friend's refresh-token
roundtrip. This worked for the old friend-profile screen because it
was rarely visited; if the new Profile becomes a destination tab, load
frequency goes up 10×+. Three options:

1. **Do nothing for v1** — accept the latency and Spotify API budget.
2. **Cache per-user top-items** in DynamoDB with a 24h TTL. Refresh
   lazily on miss. Matches how `cron_wrapped` already stores top-items
   snapshots; could reuse that table.
3. **Serve from the existing `cron_wrapped` monthly snapshot** for
   `.other` specifically — staleness is acceptable for friend-view use
   cases.

Recommend option 2 when iOS Phase 5 (`.other` Taste) ships. Not a
blocker for Phase 0 close.

---

## 4. `lastSeenAt` — out of scope for v1

Plan item 4 is marked non-blocking. Defer until after ship; then add
`lastSeenAt` to both `user_data` and `friends_profile` responses,
updated by a cheap mutation on authenticated endpoint hits (e.g.
`/shares/feed` load). Single DynamoDB `UpdateItem` per session, not
per request.

---

## Summary — what actually needs to land on the backend

| # | Change | Blocker for | Effort |
|---|--------|-------------|--------|
| 1 | Add `shareCount` to `/friends/profile` response | iOS Phase 2 | ~30 min |
| 2 | Cache `/friends/profile` top-items to cut Spotify calls | iOS Phase 5 (nice-to-have) | ~2 hrs |

Everything else is either already live or punted.

## iOS-side corrections (no backend work, pure plan edits)

- `SharesByUserResponse` cursor field is `nextBefore`, not `nextCursor`.
- `getSharesByUser` must send **both** `email` (caller) and `targetEmail`
  (target) query params.
- `.other` taste tab receives three populated term buckets by default;
  fallback triggers on empty arrays per bucket, not on missing buckets.
- `.other` taste tab receives full Spotify track/artist objects
  including album art — no text-only degradation needed.
