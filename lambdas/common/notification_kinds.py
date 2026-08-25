"""
XOMIFY Notification Kind Registry
=================================
One place that answers, for every notification the product can send:

  - what it is called on the wire (`key`)
  - which per-device opt-in flag gates it
  - whether it is on by default for a device that has never heard of it
  - how its title / body / deep link are worded
  - which Settings section it appears under
  - whether it coalesces with a sibling kind

WHY THIS EXISTS: before it, `notifications_send` carried a hardcoded
`VALID_KINDS` set and an `OPT_IN_FLAG_BY_KIND` dict, and every producer wrote
its own title and body inline. That was survivable at two kinds. At sixteen it
means sixteen places to get the copy wrong and no way to answer "what can this
app send me?" without grepping.

OPT-IN DEFAULTS: an absent flag on a device-token row reads as this registry's
`default_opt_in`. That is what lets the fourteen new kinds ship with NO
backfill — existing rows simply inherit the defaults.

The two pre-existing kinds (`queue_threshold`, `digest`) keep their exact
wire keys and their exact flag names. Renaming either would silently opt every
existing device out of something it had already chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Sections ────────────────────────────────────────────────────────────
# Purely a presentation grouping for the Settings screens (iOS + web). The
# toggles are per-KIND, not per-section (see the epic plan, decision 3).
SECTION_SHARES = "shares_social"
SECTION_DROPS = "playlist_drops"
SECTION_REMINDERS = "reminders_updates"

SECTION_LABELS = {
    SECTION_SHARES: "Shares & Social",
    SECTION_DROPS: "Playlist Drops",
    SECTION_REMINDERS: "Reminders & Updates",
}

SECTION_ORDER = [SECTION_SHARES, SECTION_DROPS, SECTION_REMINDERS]


# ── Coalescing ──────────────────────────────────────────────────────────
# Kinds sharing a `coalesce_group` AND the same subject collapse into one push
# when they land inside `coalesce_window_s` of each other. Today that is
# exactly share_listened + share_rated: one person hitting play and then
# rating is ONE act of engagement, and buzzing the sender twice for it is how
# you teach them to mute the app.
COALESCE_SHARE_ENGAGE = "share_engage"
COALESCE_WINDOW_S = 600  # 10 minutes — epic plan, decision 11


@dataclass(frozen=True)
class NotificationKind:
    key: str
    section: str
    #: Attribute name on the xomify-device-tokens row.
    opt_in_flag: str
    default_opt_in: bool
    #: `str.format(**ctx)` templates. Producers supply the context.
    title: str
    body: str
    #: Deep-link route template handed to the clients as customData.route.
    #: Client-side parsing already understands "share:<id>" and "invite:<code>".
    route: Optional[str] = None
    coalesce_group: Optional[str] = None
    #: Wording used when this kind is merged with its coalesce sibling.
    merged_title: Optional[str] = None
    merged_body: Optional[str] = None
    #: Human label for the Settings row.
    label: str = ""
    description: str = ""


_KINDS: tuple[NotificationKind, ...] = (
    # ── Shares & Social ─────────────────────────────────────────────────
    NotificationKind(
        key="share_received",
        section=SECTION_SHARES,
        opt_in_flag="shareReceivedEnabled",
        default_opt_in=True,
        title="{actor_name} sent you a song",
        body="{track_name} — {artist_name}",
        route="share:{share_id}",
        label="Someone shares a song",
        description="When a friend sends you a track.",
    ),
    NotificationKind(
        key="share_comment",
        section=SECTION_SHARES,
        opt_in_flag="shareCommentEnabled",
        default_opt_in=True,
        title="{actor_name} commented",
        body="{comment_preview}",
        route="share:{share_id}",
        label="Comments on your share",
        description="When someone replies on a song you sent.",
    ),
    NotificationKind(
        key="share_reaction",
        section=SECTION_SHARES,
        opt_in_flag="shareReactionEnabled",
        default_opt_in=True,
        title="{actor_name} reacted {emoji}",
        body="on {track_name}",
        route="share:{share_id}",
        label="Reactions on your share",
        description="When someone reacts to a song you sent.",
    ),
    NotificationKind(
        key="share_listened",
        section=SECTION_SHARES,
        opt_in_flag="shareListenedEnabled",
        default_opt_in=True,
        title="{actor_name} listened",
        body="to {track_name}",
        route="share:{share_id}",
        coalesce_group=COALESCE_SHARE_ENGAGE,
        merged_title="{actor_name} listened and rated {stars}",
        merged_body="{track_name} — {artist_name}",
        label="Someone listens to your song",
        description="When a friend plays a track you sent.",
    ),
    NotificationKind(
        key="share_rated",
        section=SECTION_SHARES,
        opt_in_flag="shareRatedEnabled",
        default_opt_in=True,
        title="{actor_name} rated {stars}",
        body="{track_name} — {artist_name}",
        route="share:{share_id}",
        coalesce_group=COALESCE_SHARE_ENGAGE,
        merged_title="{actor_name} listened and rated {stars}",
        merged_body="{track_name} — {artist_name}",
        label="Someone rates your song",
        description="When a friend scores a track you sent.",
    ),
    # PRE-EXISTING — key and flag name are load-bearing, do not rename.
    NotificationKind(
        key="queue_threshold",
        section=SECTION_SHARES,
        opt_in_flag="queueNotificationsEnabled",
        default_opt_in=True,
        title="Your share is heating up",
        body="{reactor_count} friends have queued {track_name}",
        route="share:{share_id}",
        label="Your share takes off",
        description="When several friends queue the same song you sent.",
    ),
    NotificationKind(
        key="friend_request",
        section=SECTION_SHARES,
        opt_in_flag="friendRequestEnabled",
        default_opt_in=True,
        title="{actor_name} wants to be friends",
        body="Tap to accept or decline.",
        route="friends",
        label="Friend requests",
        description="When someone sends you a friend request.",
    ),
    NotificationKind(
        key="friend_accepted",
        section=SECTION_SHARES,
        opt_in_flag="friendAcceptedEnabled",
        default_opt_in=True,
        title="{actor_name} accepted your request",
        body="You're now friends on Xomify.",
        route="friend:{actor_email}",
        label="Friend requests accepted",
        description="When someone accepts your friend request.",
    ),
    NotificationKind(
        key="invite_received",
        section=SECTION_SHARES,
        opt_in_flag="inviteReceivedEnabled",
        default_opt_in=True,
        title="{actor_name} invited you",
        body="Join them on Xomify.",
        route="invite:{invite_code}",
        label="Invites",
        description="When someone invites you to Xomify.",
    ),
    NotificationKind(
        key="invite_accepted",
        section=SECTION_SHARES,
        opt_in_flag="inviteAcceptedEnabled",
        default_opt_in=True,
        title="{actor_name} joined",
        body="Your invite was accepted.",
        route="friends",
        label="Invites accepted",
        description="When someone takes up your invite.",
    ),
    # ── Playlist Drops ──────────────────────────────────────────────────
    # These carry the SNEAK PEEK: the body names the top track so the push is
    # worth reading on its own, and the route opens the playlist directly.
    NotificationKind(
        key="wrapped_drop",
        section=SECTION_DROPS,
        opt_in_flag="wrappedDropEnabled",
        default_opt_in=True,
        title="Your {month} Wrapped is ready",
        body="Starting with {track_name} — {artist_name}",
        route="wrapped:{playlist_id}",
        label="Monthly Wrapped is ready",
        description="When your Wrapped playlist is generated.",
    ),
    NotificationKind(
        key="release_radar_drop",
        section=SECTION_DROPS,
        opt_in_flag="releaseRadarDropEnabled",
        default_opt_in=True,
        title="New releases this week",
        body="{release_count} from artists you follow, including {track_name}",
        route="release_radar:{playlist_id}",
        label="Release Radar is ready",
        description="When your weekly Release Radar is generated.",
    ),
    # ── Reminders & Updates ─────────────────────────────────────────────
    NotificationKind(
        key="rate_reminder",
        section=SECTION_REMINDERS,
        opt_in_flag="rateReminderEnabled",
        default_opt_in=True,
        title="Still haven't heard {track_name}?",
        body="{actor_name} sent it yesterday.",
        route="share:{share_id}",
        label="Reminders to listen & rate",
        description="A single nudge, a day after a song lands unplayed.",
    ),
    NotificationKind(
        key="favorites_reminder",
        section=SECTION_REMINDERS,
        opt_in_flag="favoritesReminderEnabled",
        default_opt_in=True,
        title="Set your {year} favorites",
        body="Lock in your top songs, albums and artists for the year.",
        route="favorites",
        label="Year-end favorites",
        description="A yearly nudge to record your favorites.",
    ),
    # PRE-EXISTING — key and flag name are load-bearing, do not rename.
    #
    # DELIBERATE BEHAVIOUR CHANGE: the old notifications_send read every absent
    # flag as `True` (`row.get(opt_in_flag, True)`), so a device row without
    # `digestEnabled` was silently receiving a weekly digest nobody asked for.
    # This is the one kind where that default is wrong — it is the most
    # annoyable notification in the set, and a weekly unsolicited push is how
    # an app gets muted wholesale. The iOS client has always sent the flag
    # explicitly from its Settings toggle, so rows lacking it are legacy only.
    NotificationKind(
        key="digest",
        section=SECTION_REMINDERS,
        opt_in_flag="digestEnabled",
        default_opt_in=False,
        title="Your weekly Xomify digest",
        body="{summary}",
        route="shares",
        label="Weekly digest",
        description="A weekly summary of shares and activity.",
    ),
    NotificationKind(
        key="broadcast",
        section=SECTION_REMINDERS,
        opt_in_flag="broadcastEnabled",
        default_opt_in=True,
        title="{broadcast_title}",
        body="{broadcast_body}",
        route="home",
        label="App updates",
        description="Occasional announcements about Xomify itself.",
    ),
)

BY_KEY: dict[str, NotificationKind] = {k.key: k for k in _KINDS}
ALL_KINDS: tuple[NotificationKind, ...] = _KINDS
VALID_KINDS: frozenset[str] = frozenset(BY_KEY)


def get_kind(key: str) -> Optional[NotificationKind]:
    return BY_KEY.get(key)


def default_preferences() -> dict[str, bool]:
    """The preference map a brand-new device registration starts from."""
    return {k.opt_in_flag: k.default_opt_in for k in _KINDS}


def is_opted_in(token_row: dict, kind: NotificationKind) -> bool:
    """
    Read one opt-in decision off a device-token row.

    An ABSENT flag falls back to the registry default rather than to False.
    That is the whole migration story: rows written before a kind existed keep
    working, and nobody has to backfill fourteen booleans across every device.
    """
    value = token_row.get(kind.opt_in_flag)
    if value is None:
        return kind.default_opt_in
    return bool(value)


def render(template: str, ctx: dict) -> str:
    """
    Fill a title/body template.

    Deliberately forgiving: a producer that forgets a key gets the placeholder
    left in place rather than a KeyError that takes the whole interaction down
    with it. Notification copy is never worth failing a write over.
    """
    try:
        return template.format(**ctx)
    except (KeyError, IndexError, ValueError):
        return template
