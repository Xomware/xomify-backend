"""
XOMIFY Share Visibility Helpers
===============================
Shared visibility check used by share-scoped endpoints
(shares_detail, comments, reactions). Mirrors the rule applied in
shares_detail.handler so callers stay consistent.

Rule:
- Public shares (default / `public != False`) are visible to anyone.
- Group-only shares (`public == False`) are visible to:
    1. The author themselves
    2. Members of any group in the share's `groupIds`
"""

from __future__ import annotations

from typing import Any

from lambdas.common.group_members_dynamo import is_member_of_group


def viewer_can_see_share(share: dict[str, Any], viewer_email: str) -> bool:
    """Return True if viewer should be able to read the share."""
    if not share:
        return False

    is_public = share.get("public", True)
    if is_public:
        return True

    author_email = share.get("email")
    if author_email and viewer_email == author_email:
        return True

    target_group_ids = share.get("groupIds") or []
    for gid in target_group_ids:
        if isinstance(gid, str) and gid and is_member_of_group(viewer_email, gid):
            return True

    return False
