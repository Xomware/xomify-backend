---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0a-infra
repo: xomify-infrastructure
---

# auth-login-route-and-lambda-resources

> **Status: Stub.** This is a placeholder. Run `/plan auth-login-route-and-lambda-resources` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Bump module ref to `v2.3.0` in `xomify-infrastructure/terraform/api_gateway.tf:91`.
- Add `auth_login` lambda Terraform resource (mirror existing patterns in `lambdas_user.tf`).
- Add `/auth/login` to the appropriate `services` block with `authorization = "NONE"`.
- Add IAM policy for the lambda to read the SSM secret (`API_SECRET_KEY`).
- Update `cloudwatch.tf` for the new lambda log group.

## Repo
xomify-infrastructure

## Dependencies
(0-pre) — needs v2.3.0 published.

## Exit criteria
`terraform plan` shows the new lambda + public route. `terraform apply` succeeds. `curl -X POST /auth/login` reaches the lambda (returns 200 once the (0a) backend code is also deployed; until then, deploys an empty/stub lambda artifact or 5xx is acceptable as long as the route is wired).

## Notes
- Requires Terraform apply to prod AWS — human gate.
- Use `infra-specialist` agent per epic Skills section.
