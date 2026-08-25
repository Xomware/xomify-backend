"""
Tests for the rate-reminder cron (B5).

Decision 9 is "one reminder per share, EVER". The two ways to violate that are
reminding twice and reminding someone who already engaged, so both get a test.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


def _share(share_id="s1", hours_old=30, author="author@e.com"):
    created = datetime.now(timezone.utc) - timedelta(hours=hours_old)
    return {
        "shareId": share_id,
        "email": author,
        "createdAt": created.isoformat(),
        "trackName": "Midnight City",
        "artistName": "M83",
    }


def _friends(*emails):
    return [{"friendEmail": e, "status": "accepted"} for e in emails]


@pytest.fixture
def wired():
    with patch("lambdas.cron_rate_reminder.handler.notify") as notify, \
         patch("lambdas.cron_rate_reminder.handler.display_name_for", return_value="Author"), \
         patch("lambdas.cron_rate_reminder.handler.mark_rate_reminded", return_value=True) as latch, \
         patch("lambdas.cron_rate_reminder.handler.list_listeners_for_share", return_value=[]), \
         patch("lambdas.cron_rate_reminder.handler.list_interactions_for_share", return_value=[]), \
         patch("lambdas.common.friendships_dynamo.list_all_friends_for_user",
               return_value=_friends("a@e.com", "b@e.com")):
        yield {"notify": notify, "latch": latch}


def test_reminds_the_unengaged_audience(wired):
    from lambdas.cron_rate_reminder.handler import _run

    with patch("lambdas.cron_rate_reminder.handler.scan_all_shares", return_value=[[_share()]]):
        stats = _run()

    assert stats["reminded"] == 2
    assert {c.args[1] for c in wired["notify"].call_args_list} == {"a@e.com", "b@e.com"}
    assert wired["notify"].call_args.args[0] == "rate_reminder"


def test_skips_a_share_that_is_too_young(wired):
    """A share needs a day to land before nagging anyone about it."""
    from lambdas.cron_rate_reminder.handler import _run

    with patch("lambdas.cron_rate_reminder.handler.scan_all_shares",
               return_value=[[_share(hours_old=2)]]):
        stats = _run()

    assert stats["examined"] == 0
    wired["notify"].assert_not_called()


def test_skips_a_share_past_the_window(wired):
    """
    Without an upper bound the daily scan re-examines the whole table forever.
    """
    from lambdas.cron_rate_reminder.handler import _run

    with patch("lambdas.cron_rate_reminder.handler.scan_all_shares",
               return_value=[[_share(hours_old=200)]]):
        stats = _run()

    assert stats["examined"] == 0
    wired["notify"].assert_not_called()


def test_a_lost_latch_means_another_run_owns_it(wired):
    """Once per share, ever — an overlapping run must not double-remind."""
    from lambdas.cron_rate_reminder.handler import _run

    wired["latch"].return_value = False
    with patch("lambdas.cron_rate_reminder.handler.scan_all_shares", return_value=[[_share()]]):
        stats = _run()

    assert stats["reminded"] == 0
    assert stats["skipped"] == 1
    wired["notify"].assert_not_called()


def test_does_not_nag_someone_who_already_listened():
    from lambdas.cron_rate_reminder.handler import _run

    with patch("lambdas.cron_rate_reminder.handler.notify") as notify, \
         patch("lambdas.cron_rate_reminder.handler.display_name_for", return_value="Author"), \
         patch("lambdas.cron_rate_reminder.handler.mark_rate_reminded", return_value=True), \
         patch("lambdas.cron_rate_reminder.handler.list_listeners_for_share",
               return_value=[{"email": "a@e.com"}]), \
         patch("lambdas.cron_rate_reminder.handler.list_interactions_for_share", return_value=[]), \
         patch("lambdas.common.friendships_dynamo.list_all_friends_for_user",
               return_value=_friends("a@e.com", "b@e.com")), \
         patch("lambdas.cron_rate_reminder.handler.scan_all_shares", return_value=[[_share()]]):
        stats = _run()

    assert stats["reminded"] == 1
    assert notify.call_args.args[1] == "b@e.com"


def test_a_rating_without_a_listen_still_counts_as_engaged():
    """Rating a track you never 'played' in-app is still engagement."""
    from lambdas.cron_rate_reminder.handler import _run

    with patch("lambdas.cron_rate_reminder.handler.notify") as notify, \
         patch("lambdas.cron_rate_reminder.handler.display_name_for", return_value="Author"), \
         patch("lambdas.cron_rate_reminder.handler.mark_rate_reminded", return_value=True), \
         patch("lambdas.cron_rate_reminder.handler.list_listeners_for_share", return_value=[]), \
         patch("lambdas.cron_rate_reminder.handler.list_interactions_for_share",
               return_value=[{"email": "a@e.com", "rated": True}]), \
         patch("lambdas.common.friendships_dynamo.list_all_friends_for_user",
               return_value=_friends("a@e.com", "b@e.com")), \
         patch("lambdas.cron_rate_reminder.handler.scan_all_shares", return_value=[[_share()]]):
        stats = _run()

    assert stats["reminded"] == 1
    assert notify.call_args.args[1] == "b@e.com"


def test_the_author_never_reminds_themselves(wired):
    from lambdas.cron_rate_reminder.handler import _run

    with patch("lambdas.common.friendships_dynamo.list_all_friends_for_user",
               return_value=_friends("author@e.com", "b@e.com")), \
         patch("lambdas.cron_rate_reminder.handler.scan_all_shares", return_value=[[_share()]]):
        stats = _run()

    assert stats["reminded"] == 1
    assert wired["notify"].call_args.args[1] == "b@e.com"
