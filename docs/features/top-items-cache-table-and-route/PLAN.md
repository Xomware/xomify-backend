---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 2a-infra
repo: xomify-infrastructure
---

# top-items-cache-table-and-route

> **Status: Stub.** This is a placeholder. Run `/plan top-items-cache-table-and-route` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- In `xomify-infrastructure/terraform/dynamodb.tf` add the `TOP_ITEMS_CACHE` table — PK `email`, native TTL on `ttl` attr.
- In `xomify-infrastructure/terraform/lambdas_user.tf` add the `user_top_items` lambda resource.
- Add `/user/top-items` to the `user` service endpoints block with `authorization = "CUSTOM"` (default — explicit for clarity).
- Wire env var `TOP_ITEMS_CACHE_TABLE_NAME` into the lambda.
- IAM policy grants `GetItem` + `PutItem` on the new table.
- Update `cloudwatch.tf` for the new lambda log group.

## Repo
xomify-infrastructure

## Dependencies
(0-pre) — module ref bump (already shipped via (0a-infra), no re-bump needed); (2a) backend code merged.

## Exit criteria
`terraform apply` creates the table and route. `curl GET /user/top-items` with a valid per-user JWT returns 200.

## Notes
- Use `infra-specialist` agent.
- Requires Terraform apply to prod AWS — human gate.
- Risk: "DDB TTL eviction lag (up to 48h) leaves stale rows readable" — handler-side gate on `cachedAt.date() < today_utc.date()` covers this; TTL is just a janitor.
