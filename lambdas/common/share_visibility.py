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
from lambdas.common.logger import get_logger

log = get_logger(__file__)


def viewer_can_see_share(share: dict[str, Any], viewer_email: str) -> bool:
    """Return True if viewer should be able to read the share.

    Group-membership lookups can raise on transient DDB failures. We treat
    those as "not visible" (and log) rather than letting them bubble up as a
    500 — handlers above us already convert a False result to a 404, which is
    the safer default for a visibility gate.
    """
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
        if not (isinstance(gid, str) and gid):
            continue
        try:
            if is_member_of_group(viewer_email, gid):
                return True
        except Exception as err:
            # Swallow per-group lookup failures so one bad row doesn't 500
            # the whole request; log so we can spot persistent issues.
            log.warning(
                f"viewer_can_see_share: membership lookup failed "
                f"for viewer={viewer_email} group={gid}: {err}"
            )
            continue

    return False
