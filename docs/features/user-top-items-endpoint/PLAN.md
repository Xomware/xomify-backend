---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 2a
repo: xomify-backend
---

# user-top-items-endpoint

> **Status: Stub.** This is a placeholder. Run `/plan user-top-items-endpoint` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
Backend lambda code + tests only — infra moved to (2a-infra).
- `lambdas/common/top_items_cache.py`: `get_cached(email) -> dict | None`, `set_cached(email, top_items) -> None`. `get_cached` returns None if `cachedAt.date() < today_utc.date()` (Q7).
- `lambdas/user_top_items/handler.py`: reads caller email from context (via 0c), cache-then-fetch. Per-range partial failure handled — `meta.failed_ranges` is a list of strings.
- `DEPLOYMENT_GUIDE.md` updated.
- GitHub Actions deploy matrix updated.
- Tests: `tests/test_user_top_items.py` covering cache hit, cache miss, partial Spotify failure (one range raises), TTL boundary (cachedAt yesterday-UTC = miss; cachedAt today-UTC = hit), 401 on missing context.

## Repo
xomify-backend

## Dependencies
(0c). Does NOT depend on (1*) work.

## Exit criteria
Lambda code merged; cache helper unit-tested. End-to-end exit (route live, table populated) gated on (2a-infra) apply.

## Notes
- Use `backend-standards` skill.
- Risk: "Partial-failure response shape confuses iOS deserializer" — document `meta.failed_ranges` in API contract.
