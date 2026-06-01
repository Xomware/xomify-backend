# Plan: Public Top Items Endpoint (`GET /music/public-top-items`)

**Status**: Ready
**Created**: 2026-06-01
**Last updated**: 2026-06-01 (decisions reconciled)

## Decisions Locked (2026-06-01)

These were open questions in the Draft; they are now resolved and are not up for
re-discussion during implementation. The plan below has been reconciled to match.

1. **Visibility gate = hardcoded allowlist (v1).** The `profileVisibility` field
   does not exist on the xomify users table and adding it is deferred to the
   multi-user / v2 story. v1 uses a **hardcoded allowlist of public userIds**
   (just Dom's userId for now) defined as a constant (or environment variable) in
   `lambdas/public_top_items/handler.py`. Default-deny — any userId not in the
   allowlist returns **404** (same response as unknown user, to prevent
   enumeration). The documented v2 upgrade path is to replace the allowlist with
   a real `profileVisibility` data-driven flag on the users table, requiring no
   other changes to the handler's gate logic.

2. **Endpoint home = xomify's own API gateway.** The endpoint is at
   `api.xomify.xomware.com` under a new `music` service prefix:
   `GET /music/public-top-items?userId=<id>`, `authorization = "NONE"` (no JWT).
   `https://xomware.com` must be added to `cors_allowed_origins` (currently only
   `https://xomify.xomware.com`). The `xomware-frontend` must be repointed from
   `api.xomware.com` to `api.xomify.xomware.com` for this call — tracked as a
   cross-repo frontend follow-up (a one-line env change + a new env key, e.g.
   `xomifyApiUrl` or `musicApiUrl`, since the existing `usersApiUrl` points to
   `api.xomware.com`).

Previously noted design calls that remain unchanged: 404 for private/unknown
users, v1 is `short_term` only, `nowPlaying` is a separate later plan, and the
public path is read-only-against-cache with a fallback (serve cache if present;
only fall through to a live fetch as last resort).

---

## Summary
Build a new **public, unauthenticated** endpoint that serves a single specified
user's cached top items (top tracks, artists, genres) so xomware.com can render
Dom's listening stats to anonymous visitors. This is the backend companion to
the already-built `/music` feature in `xomware-frontend` and unblocks flipping
`useMockMusicData` off. Success = `GET .../music/public-top-items?userId=<id>`
returns the flattened, top-5 shape the frontend already expects, gated so only
public profiles are exposed.

## Approach
Add a new lambda `lambdas/public_top_items/handler.py` that mirrors the existing
auth-gated `lambdas/user_top_items/handler.py` and **reuses** the same cache
(`top_items_cache.get_cached`/`set_cached`) and Spotify fetch path
(`_fetch_top_items_with_partial_tolerance`). The only structural differences:

1. **No authorizer** — the route is wired with `authorization = "NONE"` (same
   pattern as `auth/login` in `xomify-infrastructure/terraform/lambdas_auth.tf`).
   Identity comes from a `userId` **query param**, not the JWT context.
2. **userId → email resolution** — the cache and users table are keyed by
   `email`, but the public contract passes `userId`. We need a lookup
   (see Open Questions / userId resolution below).
3. **Public gate** — only serve users in the hardcoded allowlist (see Decisions
   Locked). No schema change needed for v1; the allowlist is a constant/env var
   in the new handler. Default-deny; allowlist miss → 404.
4. **Flatten + slice transform** — collapse the range-keyed `{tracks, artists,
   genres}` cache shape down to the flat top-5 `short_term`-only frontend shape.

Everything that touches Spotify or the cache is imported from existing modules —
**no Spotify logic is duplicated**. The new handler is essentially: resolve user
-> gate -> reuse cache/fetch -> transform -> respond.

### Resolved host / path
- Real API host is **`api.xomify.xomware.com`**, not `api.xomware.com`.
  Derived from `xomify-infrastructure/terraform/locals.tf`:
  `api_domain_name = "api.${app_name}${domain_suffix}"` → `api.xomify.xomware.com`.
- A new **`music` service path prefix** will be added to the API Gateway
  (`api_gateway.tf`) — locked per Decision 2. This keeps the public surface
  logically separate from the auth-gated `user` routes and matches the frontend
  contract as built.
- **Full resolved URL** the frontend env should point at:
  `https://api.xomify.xomware.com/{stage}/music/public-top-items?userId=<id>`
  (stage defaults to `dev` per `variables.tf` — prod stage name is a remaining
  open question, see below; not a blocker for writing the code).

## Affected Files / Components
| File / Component | Change | Why |
|-----------------|--------|-----|
| `lambdas/public_top_items/handler.py` (new) | New unauthenticated handler | Endpoint entry point |
| `lambdas/public_top_items/__init__.py` (new) | Package marker | Match other lambda dirs |
| `lambdas/common/dynamo_helpers.py` | Add `get_user_by_user_id(user_id)` resolver | userId→email/user lookup (see Open Questions) |
| `lambdas/common/top_items_cache.py` | Reused as-is (`get_cached`) | Daily cache, keyed by email |
| `lambdas/user_top_items/handler.py` | Possibly extract `_fetch_top_items_with_partial_tolerance` + `_TIME_RANGES` into a shared module | Avoid duplicating the partial-failure fetch; import into both handlers |
| `lambdas/common/top_items_transform.py` (new, optional) | Flatten/slice transform + `windowLabel` map | Keep handler thin; unit-testable in isolation |
| `tests/test_public_top_items.py` (new) | Mirror `tests/test_user_top_items.py` style | Cover happy/blocked/unknown/partial/cache paths |
| `xomify-infrastructure/terraform/lambdas_music.tf` (new) | New lambda + `music` service local with `authorization = "NONE"` | Provision the unauthenticated route |
| `xomify-infrastructure/terraform/api_gateway.tf` | Register `music` service prefix + endpoints | Wire route to API Gateway |
| `xomify-infrastructure/terraform/variables.tf` (`cors_allowed_origins`) | Add `https://xomware.com` to allowed origins | Endpoint is consumed by xomware.com, not xomify.xomware.com |

## Implementation Steps
- [ ] **Define the v1 allowlist constant.** In `lambdas/public_top_items/handler.py`,
      define `PUBLIC_USER_IDS` as a constant (or read from an env var
      `PUBLIC_USER_IDS` as a comma-separated string) containing Dom's userId.
      The gate check is: `if userId not in PUBLIC_USER_IDS → 404`. No schema
      changes needed. Document the v2 upgrade path (swap for a DDB flag) in a
      comment above the constant.
- [ ] **Add userId→user resolver** in `dynamo_helpers.py`
      (`get_user_by_user_id(user_id) -> dict | None`). Implement per the Open
      Question decision (GSI vs. filtered scan). Return `None` on miss (do not
      raise) so the handler can decide the response code.
- [ ] **Extract the shared fetch.** Move `_fetch_top_items_with_partial_tolerance`,
      `_safe_set_top_tracks`, `_safe_set_top_artists`, `_empty_top_items_skeleton`,
      and `_TIME_RANGES` into `lambdas/common/top_items_fetch.py`; re-import into
      `user_top_items/handler.py` (no behavior change) and the new handler.
- [ ] **Write the transform** (`top_items_transform.py`):
      `flatten_public_top_items(cache_payload, cached_at) -> dict`. Takes the
      range-keyed cache payload, reads **`short_term` only**, slices to 5, maps to
      frontend field names (below), sets `windowLabel="Last 4 weeks"`,
      `updatedAt=<cachedAt iso>`, `nowPlaying=None`.
- [ ] **Write the handler** (`public_top_items/handler.py`):
      1. read `userId` from `get_query_params(event)`; 400 if missing.
      2. `user = get_user_by_user_id(userId)`; if `None` → 404.
      3. gate: if not public → 404 (see gate decision).
      4. `cached = get_cached(user["email"])`; on hit → transform + return.
      5. on miss → `_fetch_top_items_with_partial_tolerance(user)`; write cache
         only if no failed ranges (same rule as `user_top_items`).
      6. if `short_term` failed (in `failed_ranges`) and there is no prior cached
         `short_term` to fall back to → return `200` with empty arrays +
         `updatedAt=null` (frontend renders empty gracefully) rather than 5xx.
      7. transform + `success_response(...)`.
- [ ] **Decorate** with `@handle_errors("public_top_items")` for consistent error
      shapes.
- [ ] **Provision infra** — new `lambdas_music.tf` with a `music_lambdas` local
      (`name="public-top-items"`, `path_part="public-top-items"`,
      `http_method="GET"`, `authorization="NONE"`), the
      `aws_lambda_function.music` resource (copy `lambdas_auth.tf` pattern), and a
      `music` entry in `api_gateway.tf` `services`/`locals`. Add IAM read access
      to the users + top-items-cache tables (lambda role already broad — confirm).
- [ ] **CORS** — append `https://xomware.com` to `cors_allowed_origins`
      (currently only `https://xomify.xomware.com`). Note the lambda's own
      `CORS_HEADERS` already sends `Access-Control-Allow-Origin: *`, but the API
      Gateway module CORS config is the gate that matters for browsers.
- [ ] **Tests** — `tests/test_public_top_items.py` (see Tests section).
- [ ] **Report frontend env values** — confirm prod stage name and hand the
      resolved base URL to the `xomware-frontend` `environment.ts` owner.

### Frontend contract (target shape — pinned, do not drift)
```jsonc
{
  "topTracks":  [{ "name": "...", "artist": "...", "albumArt": "...", "url": "..." }], // <=5
  "topArtists": [{ "name": "...", "image": "...", "url": "..." }],                     // <=5
  "topGenres":  [{ "genre": "...", "count": 0 }],                                      // <=5
  "windowLabel": "Last 4 weeks",   // short_term
  "updatedAt": "<iso>",             // from cache cachedAt
  "nowPlaying": null                // v2
}
```

### Transform mapping (from cache `short_term` raw Spotify objects)
Confirmed against `tests/conftest.py::sample_top_items` and `track_list.py` /
`artist_list.py` (cache stores raw Spotify `items`):
- **track** → `name=t["name"]`,
  `artist=", ".join(a["name"] for a in t.get("artists", []))`,
  `albumArt=(t.get("album", {}).get("images") or [{}])[0].get("url")`,
  `url=(t.get("external_urls") or {}).get("spotify")`. Defensive `.get()` on all —
  the conftest sample omits `album`/`external_urls`, real payloads include them.
- **artist** → `name=a["name"]`,
  `image=(a.get("images") or [{}])[0].get("url")`,
  `url=(a.get("external_urls") or {}).get("spotify")`.
- **genres** → cache `genres.short_term` is a `{genre: count}` dict; convert to
  `[{genre, count}]` sorted by count desc, top 5.

## Out of Scope
- **Now-playing (`nowPlaying`)** — v2. Requires a new Spotify scope
  (`user-read-currently-playing`) and a separate live (non-cached) endpoint.
  This plan hard-codes `nowPlaying: null`.
- **medium_term / long_term** windows — v1 is `short_term` only.
- **Multi-user / arbitrary public directory** — endpoint serves whatever
  `userId` is passed but the only intended consumer is Dom's stats on the
  landing page.
- **Writing `profileVisibility`** UI/flows — this plan only *reads* the gate;
  populating it is a dependency (see Risks) handled wherever user records are
  written (`user_update`, auth login).
- **Rewriting the auth-gated `/user/top-items`** — only a non-behavioral refactor
  to share the fetch helper.

## Risks / Tradeoffs
- **Gate field resolved — v1 allowlist (no schema change).** `profileVisibility`
  does not exist on the xomify users table and is not added in this plan. The v1
  gate is a hardcoded `PUBLIC_USER_IDS` allowlist in the handler (see Decisions
  Locked). Default-deny is enforced; the v2 path (replace with a DDB flag) is
  documented in code. No risk of accidentally exposing a private user.
- **No userId GSI on the users table.** `aws_dynamodb_table.users` is `hash_key
  = "email"` only (dynamodb.tf). A `get_user_by_user_id` must either add a GSI
  (`userId-index`, infra change + backfill) or do a filtered `scan` (cheap at
  this table size for a personal app, but O(n) and a full-table read).
  Recommendation: **filtered scan for v1** (small table, single intended user),
  flag GSI as the scale-up path. Document the tradeoff explicitly.
- **Public + unauthenticated exposure.** Only public top items are returned —
  no email, no tokens, no refreshToken (transform reads only name/art/url/genre).
  Risks: (1) scraping / cost from repeated calls — mitigated by the daily DDB
  cache (a hit costs one `get_item`, no Spotify call); consider API Gateway
  throttling / a WAF rate rule (infra already references waf modules) but do
  **not** over-engineer for a personal project. (2) User enumeration — returning
  **404 for both unknown userId and private user** avoids leaking which userIds
  exist (see below).
- **403 vs 404 for non-public users.** **Recommendation: 404.** A 403 confirms
  the userId exists but is private (information leak / enumeration aid). 404
  collapses "unknown" and "private" into one indistinguishable response, which is
  the safer default for an unauthenticated public endpoint. Tradeoff: slightly
  less precise for debugging — acceptable.
- **Host/path locked.** Endpoint is `api.xomify.xomware.com` with a new `music`
  service prefix (see Decisions Locked). The frontend will be repointed as a
  cross-repo follow-up (new env key, one-line change). Track that follow-up;
  until it ships, `useMockMusicData` stays on.
- **CORS origin locked.** `https://xomware.com` must be added to
  `cors_allowed_origins` in the infra Terraform — included in the implementation
  steps. No browser requests will succeed until this is deployed.
- **Partial-failure on `short_term`.** If the live fetch fails specifically for
  `short_term` and there's no fresh cache, the response would have no tracks.
  Mitigation: return 200 with empty arrays + `updatedAt: null` so the frontend
  degrades gracefully rather than 5xx-ing the landing page.

## Open Questions
- [x] **Where does the public gate flag live?** **Resolved (2026-06-01):** v1
      hardcoded allowlist in the handler. `profileVisibility` is deferred to v2.
      See Decisions Locked.
- [ ] **userId resolution: GSI or scan?** Recommendation scan for v1 — confirm
      acceptable, or add `userId-index` GSI to `dynamodb.tf`.
- [x] **Add a `music` API service prefix, or nest under `user`?** **Resolved
      (2026-06-01):** `music` prefix. See Decisions Locked.
- [ ] **Confirm the production API stage name** (default `dev` in variables.tf)
      so the frontend base URL is exact. (Deploy-time; not a blocker for code.)
- [x] **Read-only-against-cache vs. live Spotify fetch on cache miss?**
      **Resolved (2026-06-01):** read-only-with-fallback — serve cache if present;
      only fall through to a live fetch as last resort. Locked. See implementation
      steps for the fallback path detail.

## Tests (`tests/test_public_top_items.py`, mirror `test_user_top_items.py`)
- [ ] **Public user, cache hit** — `get_user_by_user_id` returns a public user,
      `get_cached` returns a payload → 200, flattened shape, `<=5` items each,
      `windowLabel="Last 4 weeks"`, `updatedAt` set, `nowPlaying` null, no Spotify
      call.
- [ ] **Public user, cache miss + full success** — fetch path invoked, cache
      written, transformed 200.
- [ ] **Private (non-public) user** — gate fails → **404** (no body leak of
      existence).
- [ ] **Unknown userId** — `get_user_by_user_id` returns None → **404**.
- [ ] **Missing `userId` query param** → **400**.
- [ ] **Partial failure on `short_term`, no cache** → 200 with empty arrays +
      `updatedAt: null`, cache NOT written.
- [ ] **Transform unit tests** — top-5 slicing, multi-artist join, missing
      `album`/`external_urls` (conftest sample shape) handled defensively, genre
      dict→sorted list.
- [ ] **Reuse the conftest `sample_top_items` / `sample_user` fixtures**; add a
      `public` flag to a user fixture once the gate field is decided.

## Forward Look: Public Music Hub (out of scope for this plan)
This endpoint is the first of three planned "public music hub" endpoints. The
siblings follow the same allowlist + CORS + flatten pattern and will get their
own plans:

- **`public-release-radar`** — same allowlist/CORS/flatten approach, different
  cache key / Spotify data shape.
- **`public-wrapped`** — same allowlist/CORS/flatten approach, but the wrapped
  store holds only `topSongIds`/`topArtistIds` (Spotify track/artist IDs), so
  the handler must hydrate those IDs to full objects via the Spotify API before
  transforming. This is an additional implementation step not needed here.

This plan stays scoped to top-items. Do not expand scope into the siblings here.

---

## Skills / Agents to Use
- **brainstorm agent** — only if the gate-field decision (Open Q1) needs options
  weighed before implementation; otherwise skip.
- **execute / implementer** — once Status flips to `Ready`, implement steps in
  order (gate decision → resolver → shared fetch extract → transform → handler →
  infra → tests).
- **test-runner** — run `npm`-equivalent `pytest` for the new
  `tests/test_public_top_items.py` and the unchanged `test_user_top_items.py`
  (the refactor must not break it).
