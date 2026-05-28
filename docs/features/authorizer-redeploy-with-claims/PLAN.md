---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0b-infra
repo: xomify-infrastructure
---

# authorizer-redeploy-with-claims

> **Status: Stub.** This is a placeholder. Run `/plan authorizer-redeploy-with-claims` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Ensure the authorizer lambda's deploy artifact in AWS reflects the new dual-mode behavior from (0b).
- Verify whether `terraform/lambda_authorizer.tf` needs a `source_code_hash` bump or whether the deploy is artifact-driven via CI in `xomify-backend` (if CI pushes the zip, this sub-feature may be a no-op Terraform PR + a manual workflow trigger).
- Confirm via CloudWatch that the live authorizer is on the new version.

## Repo
xomify-infrastructure (and possibly the backend deploy workflow)

## Dependencies
(0b) backend code merged.

## Exit criteria
CloudWatch shows authorizer log version reflecting the new code. A request bearing a per-user JWT lands at a stub handler with `requestContext.authorizer = { email, userId }`. A request with the legacy static token still passes through with no context.

## Notes
- Open action item from epic: confirm authorizer deploy mechanism — does `terraform apply` push the lambda zip, or is that a separate GH Actions workflow in `xomify-backend`? Determines whether this sub-feature is real Terraform work or a workflow trigger + verification step.
- Use `infra-specialist` agent.
- Requires AWS deploy + CloudWatch verification — human gate.
