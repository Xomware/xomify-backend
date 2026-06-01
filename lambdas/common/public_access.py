"""
Public visibility gate for the unauthenticated `/music/*` endpoints.

Shared across `public_top_items`, `public_release_radar`, and `public_wrapped`
so the allowlist lives in exactly one place (no divergence across endpoints).

v1 gate is a hardcoded allowlist of public Spotify userIds. Default-deny — any
userId not in this set is treated as not-found (the caller returns 404, same as
an unknown user) to avoid enumeration. v1 contains only Dom's userId
(open.spotify.com/user/12146721999).

v2 upgrade path: replace this constant with a data-driven `profileVisibility`
flag on the users table. `is_public` is the only thing that changes — the
handlers are agnostic to how "public" is decided.

Optionally overridable via the `PUBLIC_USER_IDS` env var (comma-separated) so
infra can inject the real id without a code change.
"""

import os


def load_public_user_ids() -> frozenset[str]:
    """Resolve the public-user allowlist from env, falling back to the default."""
    raw = os.environ.get("PUBLIC_USER_IDS", "")
    env_ids = {uid.strip() for uid in raw.split(",") if uid.strip()}
    if env_ids:
        return frozenset(env_ids)
    return frozenset({"12146721999"})


PUBLIC_USER_IDS = load_public_user_ids()


def is_public(user_id: str, allowlist: frozenset[str] | None = None) -> bool:
    """
    Default-deny gate: only allowlisted userIds are public.

    `allowlist` lets a handler pass its own module-level copy of the set so
    tests can patch the constant on the handler module (the established pattern
    for `public_top_items`). Defaults to this module's `PUBLIC_USER_IDS`.
    """
    ids = PUBLIC_USER_IDS if allowlist is None else allowlist
    return user_id in ids
