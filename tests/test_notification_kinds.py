"""
Tests for the notification kind registry.

The registry is the contract every producer and both clients read from, so the
invariants worth guarding are structural: no duplicate wire keys, no duplicate
opt-in flags (two kinds sharing a flag means one toggle silently controls two
notifications), and no drift in the two pre-existing kinds.
"""

import pytest

from lambdas.common.notification_kinds import (
    ALL_KINDS,
    BY_KEY,
    SECTION_ORDER,
    default_preferences,
    get_kind,
    is_opted_in,
    render,
)


def test_keys_are_unique():
    keys = [k.key for k in ALL_KINDS]
    assert len(keys) == len(set(keys))


def test_opt_in_flags_are_unique():
    """Two kinds sharing a flag would make one Settings toggle mute both."""
    flags = [k.opt_in_flag for k in ALL_KINDS]
    assert len(flags) == len(set(flags))


def test_every_kind_has_a_known_section():
    for kind in ALL_KINDS:
        assert kind.section in SECTION_ORDER


def test_every_kind_has_label_and_copy():
    for kind in ALL_KINDS:
        assert kind.label, f"{kind.key} has no Settings label"
        assert kind.title and kind.body, f"{kind.key} has no copy"


@pytest.mark.parametrize(
    "key,flag",
    [("queue_threshold", "queueNotificationsEnabled"), ("digest", "digestEnabled")],
)
def test_preexisting_kinds_keep_their_wire_contract(key, flag):
    """
    Renaming either of these silently opts every existing device out of
    something it had already chosen.
    """
    kind = get_kind(key)
    assert kind is not None
    assert kind.opt_in_flag == flag


def test_default_preferences_cover_every_kind():
    prefs = default_preferences()
    assert len(prefs) == len(ALL_KINDS)
    for kind in ALL_KINDS:
        assert kind.opt_in_flag in prefs


def test_digest_is_the_only_kind_off_by_default():
    """
    Deliberate change from the old blanket `row.get(flag, True)`: a device row
    with no digestEnabled was receiving a weekly push nobody opted into.
    """
    off = [f for f, v in default_preferences().items() if not v]
    assert off == ["digestEnabled"]


def test_absent_flag_falls_back_to_kind_default_not_false():
    """This is the whole no-backfill migration story."""
    kind = get_kind("share_received")
    assert is_opted_in({}, kind) is True

    digest = get_kind("digest")
    assert is_opted_in({}, digest) is False


def test_explicit_flag_beats_the_default():
    kind = get_kind("share_received")
    assert is_opted_in({"shareReceivedEnabled": False}, kind) is False

    digest = get_kind("digest")
    assert is_opted_in({"digestEnabled": True}, digest) is True


def test_coalescing_pair_shares_a_group_and_merged_copy():
    listened = get_kind("share_listened")
    rated = get_kind("share_rated")
    assert listened.coalesce_group == rated.coalesce_group
    assert listened.coalesce_group is not None
    assert listened.merged_title == rated.merged_title


def test_render_is_forgiving_of_missing_context():
    """Notification copy is never worth failing the interaction over."""
    assert render("{a} and {b}", {"a": "x"}) == "{a} and {b}"
    assert render("{a} only", {"a": "x"}) == "x only"


def test_unknown_kind_returns_none():
    assert get_kind("no_such_kind") is None
    assert "no_such_kind" not in BY_KEY
