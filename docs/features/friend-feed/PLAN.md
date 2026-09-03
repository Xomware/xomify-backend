# Friends on the pages that already show this data

**Status:** Shipped — steps 1-4. Step 5 dropped.
**Repos:** `xomify-backend`, `xomify-infrastructure`, `xomify-frontend`, `xomify-ios`

## The shape

Not a separate Feed destination. Each screen that already renders an artefact
gains a **Me / Friends** switch, and the Friends side shows the same thing for
people you follow.

| Screen | Friends side shows | Opens |
|---|---|---|
| Wrapped | their monthly top tracks / artists / genres | their full Wrapped |
| Release Radar | new releases from artists they follow | the playlist, previewable |
| Music Taste | their top songs, artists, genres | their full breakdown |
| ~~Shares~~ | ~~what friends were sent~~ | dropped, see below |

### Why this beats a Feed destination

Dominick landed on this and it is the right call. Wrapped is monthly and
Release Radar weekly, so with a handful of friends a dedicated feed would show
roughly **three cards a week** — a destination that is empty most days teaches
people to stop opening it.

Putting friends where the data already lives means:

- **Nothing new to discover.** You are on Wrapped; your friends' Wrapped is one
  tap away, in the place you already went looking for Wrapped.
- **Each screen keeps its own rendering.** No second card language to build or
  keep in sync with the real one.
- **It degrades well.** Zero friends means one empty tab on a page that still
  works, not an empty destination in the drawer.
- **Nothing is thrown away.** If a combined feed is wanted later, these
  friend-scoped endpoints are exactly what it would read.

## What already exists

| Piece | Where | Reusable? |
|---|---|---|
| Friend graph | `lambdas/friends_*` (8 endpoints) | yes, directly |
| Friend profile with top items | `lambdas/friends_profile` | yes — the pattern to copy |
| Wrapped archive per user | `lambdas/wrapped_all`, `cron_wrapped` | needs a friend-scoped read |
| Release Radar snapshots | `lambdas/release_radar_*` | same |
| Cached top items, 1/user/day | `/user/top-items` + cache table | same |
| Track preview + play | iOS `trackContextMenu`, `QueueButton` | yes |
| Public read-only variants | `lambdas/public_*` | **no** — see below |

**The public endpoints do not fit.** They are unauthenticated and gated by a
single-user allowlist in `lambdas/common/public_access.py`, built so
xomware.com can render Dom's stats anonymously. Reusing them would mean
allowlisting every user, making everyone's stats public to the internet. These
need authed, friend-scoped reads: same data, different door.

## The privacy gap

The only per-user visibility flag anywhere is `likesPublic`. Wrapped, Release
Radar and top items have **none** — nothing has ever shown them to another
person.

Turning this on by default retroactively publishes what every existing user
already has stored, without them choosing to. That is the one decision left.

## Decomposition

Vertical slices, each mergeable alone.

### 1. Visibility flags  (~80 lines: backend + settings UI)

`wrappedVisibility`, `releaseRadarVisibility`, `topItemsVisibility` on the user
record: `friends | private`.

Ships first and alone — the control exists before anything can read it.

### 2. Friend-scoped reads  (~120 lines, backend)

`GET /friends/wrapped?email=`, `/friends/release-radar?email=`,
`/friends/top-items?email=`.

Each asserts an **accepted** friendship, then the visibility flag, then serves
the same payload the owner sees. Fails **closed**: unreadable flag, no data.

Mirrors `friends_profile`, which already does exactly this for top items.

### 3. Me / Friends switch  (~150 lines each, iOS + web)

One screen at a time, in this order: **Wrapped → Release Radar → Music Taste**.
Wrapped first — it is the one with the most to look at.

The Friends side lists friends with the artefact; picking one renders it with
the screen's existing views.

### 4. Release Radar playlist preview  (~80 lines, iOS)

Open a friend's Release Radar playlist and preview tracks in place. The
30-second preview path already exists.

### 5. Shares: friends + repost — DROPPED

The Shares screen already has a direction filter; friends becomes a third
position. Repost writes a new share owned by you, referencing the original.

Reposts go to Xomify's own `/shares/*`, not Xomtracks. An ingested Xomtracks
share is a record of something that **happened** over iMessage; a repost is
something you **authored**. Mixing them makes the Shares screen mean two
different things.

**Dropped 2026-09-03.** The other four artefacts show YOUR data — your recap,
your radar, your taste. Shares shows what other people sent you over iMessage:
someone else's content, texted privately, which makes it the most
privacy-sensitive of the five while being the least about you.

The friends filter was also the most expensive half. Xomtracks scopes share
listing to the caller's own owner id and holds no knowledge of the Xomify
friend graph, so it needed a new trust path between two products that do not
currently talk.

Repost was never blocked — it writes to Xomify's own `/shares/*` and needs no
Xomtracks involvement. It only ever needed a destination decided. If it comes
back, it comes back on its own, without the friends filter.

## Decided

**Default visibility is `friends`, for existing users too.** Dominick's call,
made with the tradeoff on the table: it publishes to friends what people
already have stored without them choosing to, and cannot be undone for anyone
who sees it first.

Two things this buys and one it costs, recorded so the reasoning survives:
the feature works the day it ships rather than waiting for opt-in; a handful of
users who all know each other is a different privacy setting from a public app;
and the cost is that the first anyone hears of it is seeing their stats already
visible. The settings toggle from step 1 is what makes that reversible, so it
still ships first.

## Shipped

Steps 1-4, on web and iOS both:

- visibility flags on the user record, defaulting to `friends`
- `/friends/wrapped`, `/friends/release-radar`, `/friends/top-items`
- the Me/Friends switch on Wrapped, Release Radar and Music Taste
- the three visibility toggles in settings
- opening the week's Release Radar playlist in Spotify

iOS 1.21.1. Web is continuously deployed.

## Not in scope

- A combined feed destination. The endpoints here would serve one later.
- Comments or reactions.
- Notifications for friend activity.
- Friend-of-friend visibility. Accepted friends only.
