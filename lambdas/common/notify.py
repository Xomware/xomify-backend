"""
XOMIFY Notification Dispatch Helper
===================================
The single entry point every producer uses:

    from lambdas.common.notify import notify
    notify("share_received", recipient_email, actor_email=sender, share_id=..., ...)

It resolves the kind from the registry, renders title/body/route, writes the
inbox row, applies coalescing where the kind asks for it, and async-invokes
`notifications_send`.

INBOX AND PUSH ARE INDEPENDENT. The inbox row is written even when the device
has that kind muted, and even when the user has no device at all — muting a
push means "do not interrupt me", not "hide this from my history". Web has no
APNs token at all and would otherwise have an permanently empty inbox.

TWO RULES, both non-negotiable:

1. FAIL-OPEN. A notification must never take down the interaction that
   triggered it. Every path here swallows its own exceptions and logs, exactly
   like `record_notification` already does for the send log. Nobody's comment
   should fail to post because APNs had a bad afternoon.

2. NEVER NOTIFY YOURSELF. Commenting on your own share, rating a song you sent
   yourself, accepting your own invite — all reachable, all pointless as a
   push. `actor_email == recipient_email` short-circuits before anything else.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import boto3

from lambdas.common.constants import NOTIFICATIONS_SEND_FUNCTION_NAME
from lambdas.common.logger import get_logger
from lambdas.common.notification_kinds import (
    COALESCE_WINDOW_S,
    NotificationKind,
    get_kind,
    render,
)
from lambdas.common.notification_pending_dynamo import (
    claim_or_merge,
    coalesce_key,
)
from lambdas.common.notifications_dynamo import put_notification

log = get_logger(__file__)

_lambda_client = boto3.client("lambda")


def notify(
    kind_key: str,
    recipient_email: str,
    *,
    actor_email: Optional[str] = None,
    subject_id: Optional[str] = None,
    **ctx: Any,
) -> None:
    """
    Send one notification. Fire-and-forget; never raises.

    Args:
        kind_key:        registry key, e.g. "share_received".
        recipient_email: who is being notified.
        actor_email:     who caused it, when there is a person behind it. Used
                         both to suppress self-notification and to key the
                         coalescing window.
        subject_id:      the thing being acted on (usually a shareId). Required
                         for coalescing kinds; ignored otherwise.
        **ctx:           template context for title/body/route.
    """
    try:
        _notify(kind_key, recipient_email, actor_email, subject_id, ctx)
    except Exception as err:  # noqa: BLE001 — fail-open is the contract
        log.error(f"notify({kind_key}) failed for {recipient_email}: {err}")


def _notify(
    kind_key: str,
    recipient_email: str,
    actor_email: Optional[str],
    subject_id: Optional[str],
    ctx: dict[str, Any],
) -> None:
    kind = get_kind(kind_key)
    if kind is None:
        log.error(f"notify called with unknown kind '{kind_key}' — dropping")
        return

    if not recipient_email:
        log.warning(f"notify({kind_key}) with no recipient — dropping")
        return

    if actor_email and actor_email == recipient_email:
        log.info(f"notify({kind_key}) suppressed — actor is the recipient")
        return

    full_ctx = dict(ctx)
    if actor_email:
        full_ctx.setdefault("actor_email", actor_email)

    # ── Coalescing ──────────────────────────────────────────────────────
    if kind.coalesce_group and subject_id and actor_email:
        key = coalesce_key(recipient_email, kind.coalesce_group, f"{actor_email}#{subject_id}")
        outcome = claim_or_merge(
            key=key,
            kind=kind.key,
            recipient_email=recipient_email,
            ctx=full_ctx,
            window_s=COALESCE_WINDOW_S,
        )
        if outcome is None:
            # Parked. The sibling event merges with it, or the sweeper sends it.
            log.info(f"notify({kind_key}) parked for coalescing: {key}")
            return
        if outcome.get("merged"):
            _dispatch(kind, recipient_email, outcome["ctx"], merged=True)
            return
        full_ctx = outcome.get("ctx", full_ctx)

    _dispatch(kind, recipient_email, full_ctx, merged=False)


def _dispatch(
    kind: NotificationKind,
    recipient_email: str,
    ctx: dict[str, Any],
    *,
    merged: bool,
) -> None:
    """Write the inbox row, then async-invoke notifications_send."""
    title_tpl = (kind.merged_title if merged and kind.merged_title else kind.title)
    body_tpl = (kind.merged_body if merged and kind.merged_body else kind.body)

    title = render(title_tpl, ctx)
    body_text = render(body_tpl, ctx)
    route = render(kind.route, ctx) if kind.route else None

    # Inbox first, and unconditionally — see the module docstring. A user with
    # this kind muted, or on web with no APNs token at all, still gets history.
    put_notification(
        email=recipient_email,
        kind=kind.key,
        title=title,
        body=body_text,
        route=route,
        actor_email=ctx.get("actor_email"),
        actor_name=ctx.get("actor_name"),
        image_url=ctx.get("image_url"),
    )

    if not NOTIFICATIONS_SEND_FUNCTION_NAME:
        log.warning("NOTIFICATIONS_SEND_FUNCTION_NAME unset — skipping push")
        return

    event: dict[str, Any] = {
        "kind": kind.key,
        "email": recipient_email,
        "title": title,
        "body": body_text,
        "customData": {
            **{k: v for k, v in ctx.items() if v is not None},
            "route": route,
            "pushType": kind.key,
        },
    }

    try:
        _lambda_client.invoke(
            FunctionName=NOTIFICATIONS_SEND_FUNCTION_NAME,
            InvocationType="Event",  # async — never block the interaction
            Payload=json.dumps(event, default=str).encode("utf-8"),
        )
        log.info(f"notify({kind.key}) dispatched to {recipient_email} (merged={merged})")
    except Exception as err:  # noqa: BLE001
        log.error(f"Failed to invoke notifications_send for {kind.key}: {err}")


def dispatch_pending(row: dict[str, Any]) -> None:
    """
    Send a coalesced notification whose window lapsed with no sibling.

    Called by the sweeper (see cron_notification_sweeper). Rendered with the
    kind's OWN wording, not the merged wording — a listen with no rating is
    just a listen.
    """
    kind = get_kind(row.get("kind", ""))
    recipient = row.get("recipientEmail")
    if kind is None or not recipient:
        log.error(f"dispatch_pending: unusable row {row!r}")
        return
    _dispatch(kind, recipient, dict(row.get("ctx") or {}), merged=False)
