---
status: Stub
created: 2026-04-26
owner: Dominick
parent_epic: auth-identity-and-live-top-items
parent_epic_path: ../auth-identity-and-live-top-items/PLAN.md
sub_feature_id: 0-pre
repo: api-gateway-service
---

# module-per-endpoint-auth-override

> **Status: Stub.** This is a placeholder. Run `/plan module-per-endpoint-auth-override` to flesh it out before `/execute`.

## Parent epic
See [`PLAN.md`](../auth-identity-and-live-top-items/PLAN.md) for full epic context, decisions, sequencing, and risks.

## Scope
- Extend the `api-gateway-service` Terraform module so each entry in `services.<service>.endpoints[]` can opt out of (or override) the shared authorizer via an optional `authorization` field. Default behavior (when unset): use `var.authorization`, which preserves today's API.
- Backwards-compatible. Existing callers see no change.
- Tag and publish as **v2.3.0**.
- Add a module-level test (or example) that confirms a NONE-auth endpoint and a CUSTOM-auth endpoint coexist in the same API GW deploy.

## Repo
api-gateway-service (external; user owns; not cloned locally — clone first at execution)

## Dependencies
none. Track 0 prerequisite — ships before everything else.

## Exit criteria
v2.3.0 tagged. Test confirms mixed-auth endpoints in a single deploy. Bumping `xomify-infrastructure` to v2.3.0 with no per-endpoint overrides set produces a no-op `terraform plan`.

## Notes
- External repo — not present in `/Users/dom/Code/`. Execution agent must clone `git::https://github.com/domgiordano/api-gateway-service.git` first.
- Open action item from epic: confirm tagging convention and who can publish (user owns; presumably `git tag v2.3.0 && git push --tags`).
