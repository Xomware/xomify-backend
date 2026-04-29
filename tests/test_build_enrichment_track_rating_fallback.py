"""
Regression test for build_enrichment's fallback into the canonical
track-ratings table when the share-interactions table doesn't carry
a rating for the viewer/sharer.

Bug: rating from a feed card calls /ratings/publish (writes track_ratings)
but does NOT write a share_interactions row. The next /shares/feed call
returned viewerRating=None even though the user had rated the track --
the rating was visible on the Ratings page but not on the same feed card.
"""

from unittest.mock import patch

from lambdas.common.interactions_dynamo import build_enrichment


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_viewer_rating_falls_back_to_track_ratings_when_no_interactions_row(
    mock_list, mock_track,
):
    mock_list.return_value = []  # no interactions written for this share
    mock_track.side_effect = lambda email, track_id: 4.0 if email == "viewer@x.com" else None

    result = build_enrichment(
        "share-1",
        "viewer@x.com",
        track_id="track-1",
        sharer_email="author@x.com",
    )

    assert result["viewerRating"] == 4.0
    assert result["sharerRating"] is None
    mock_track.assert_any_call("viewer@x.com", "track-1")


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_sharer_rating_falls_back_to_track_ratings(mock_list, mock_track):
    mock_list.return_value = []
    mock_track.side_effect = lambda email, track_id: 5.0 if email == "author@x.com" else None

    result = build_enrichment(
        "share-1",
        "viewer@x.com",
        track_id="track-1",
        sharer_email="author@x.com",
    )

    assert result["sharerRating"] == 5.0


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_interactions_row_takes_precedence_over_track_rating_fallback(
    mock_list, mock_track,
):
    """If an interactions row already carries a rating, don't shadow it."""
    mock_list.return_value = [
        {"email": "viewer@x.com", "rated": True, "rating": 3},
    ]
    mock_track.return_value = 999.0  # would override if fallback ran

    result = build_enrichment(
        "share-1",
        "viewer@x.com",
        track_id="track-1",
        sharer_email="author@x.com",
    )

    assert result["viewerRating"] == 3.0
    # _track_rating_value still called for sharer (no interactions row), but
    # not for viewer.
    track_calls = [args for args, _ in mock_track.call_args_list]
    assert ("viewer@x.com", "track-1") not in track_calls


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_no_track_id_skips_fallback(mock_list, mock_track):
    """Older callers that don't pass track_id keep the legacy behaviour."""
    mock_list.return_value = []

    result = build_enrichment("share-1", "viewer@x.com")

    assert result["viewerRating"] is None
    assert result["sharerRating"] is None
    mock_track.assert_not_called()


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_own_post_does_not_double_count_viewer_as_sharer(mock_list, mock_track):
    """When viewer == sharer (own post) and the rating only lives in
    track_ratings, ratedCount must not double-count the same person."""
    mock_list.return_value = []
    mock_track.return_value = 4.0  # both lookups hit the same Dom rating

    result = build_enrichment(
        "share-1",
        "dom@x.com",
        track_id="track-1",
        sharer_email="dom@x.com",  # own post
    )

    assert result["viewerRating"] == 4.0
    assert result["sharerRating"] == 4.0
    assert result["ratedCount"] == 0  # viewer excluded; sharer == viewer


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_rated_count_excludes_viewer(mock_list, mock_track):
    """The viewer's own rating row never inflates ratedCount — the iOS
    card surfaces myRating separately, so 'X rated' means others."""
    mock_list.return_value = [
        {"email": "viewer@x.com", "rated": True, "rating": 3},
        {"email": "friend@x.com", "rated": True, "rating": 5},
    ]
    mock_track.return_value = None

    result = build_enrichment(
        "share-1",
        "viewer@x.com",
        track_id="track-1",
        sharer_email="author@x.com",
    )

    assert result["ratedCount"] == 1  # only friend@x.com counts


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_queued_count_excludes_viewer(mock_list, mock_track):
    """Same exclusion rule for queuedCount — viewerHasQueued is the viewer's
    own state; the count is for everyone else."""
    mock_list.return_value = [
        {"email": "viewer@x.com", "queued": True},
        {"email": "friend1@x.com", "queued": True},
        {"email": "friend2@x.com", "queued": True},
    ]
    mock_track.return_value = None

    result = build_enrichment("share-1", "viewer@x.com")

    assert result["queuedCount"] == 2
    assert result["viewerHasQueued"] is True


@patch('lambdas.common.interactions_dynamo._track_rating_value')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_sharer_rating_via_fallback_adds_to_rated_count(mock_list, mock_track):
    """A sharer who rated only via /ratings/publish (no interactions row)
    should still show up in ratedCount so the count matches what
    shares_detail's friendRatings list will render."""
    mock_list.return_value = []
    mock_track.side_effect = lambda email, track_id: 5.0 if email == "author@x.com" else None

    result = build_enrichment(
        "share-1",
        "viewer@x.com",
        track_id="track-1",
        sharer_email="author@x.com",
    )

    assert result["sharerRating"] == 5.0
    assert result["ratedCount"] == 1  # author counted


# ============================================================================
# Listener-state surfacing on the enrichment payload (Bug 2 / Bug 3 plumbing).
# build_enrichment now reads share-listeners and returns viewerHasListened +
# listenerCount alongside the existing fields.
# ============================================================================
@patch('lambdas.common.share_listeners_dynamo.count_listeners')
@patch('lambdas.common.share_listeners_dynamo.has_listened')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_enrichment_surfaces_listener_state(mock_list, mock_has, mock_count):
    mock_list.return_value = []
    mock_has.return_value = True
    mock_count.return_value = 4

    result = build_enrichment("share-1", "viewer@x.com")

    assert result["viewerHasListened"] is True
    assert result["listenerCount"] == 4
    mock_has.assert_called_once_with("share-1", "viewer@x.com")
    mock_count.assert_called_once_with("share-1")


@patch('lambdas.common.share_listeners_dynamo.count_listeners')
@patch('lambdas.common.share_listeners_dynamo.has_listened')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_enrichment_listener_helpers_default_false_zero(mock_list, mock_has, mock_count):
    """Empty listener helpers must surface as viewerHasListened=False / listenerCount=0."""
    mock_list.return_value = []
    mock_has.return_value = False
    mock_count.return_value = 0

    result = build_enrichment("share-1", "viewer@x.com")

    assert result["viewerHasListened"] is False
    assert result["listenerCount"] == 0


@patch('lambdas.common.share_listeners_dynamo.count_listeners')
@patch('lambdas.common.share_listeners_dynamo.has_listened')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_enrichment_listener_helper_failure_is_swallowed(mock_list, mock_has, mock_count):
    """A listeners-table miss / blow-up must NOT break the rest of enrichment."""
    mock_list.return_value = []
    mock_has.side_effect = RuntimeError("listeners ddb down")
    mock_count.side_effect = RuntimeError("listeners ddb down")

    result = build_enrichment("share-1", "viewer@x.com")

    # Defaults applied gracefully.
    assert result["viewerHasListened"] is False
    assert result["listenerCount"] == 0
    # And the rest of the payload is intact.
    assert result["queuedCount"] == 0
    assert result["ratedCount"] == 0


@patch('lambdas.common.share_listeners_dynamo.count_listeners')
@patch('lambdas.common.share_listeners_dynamo.has_listened')
@patch('lambdas.common.interactions_dynamo.list_reactions_for_share')
def test_enrichment_skips_listener_check_when_disabled(mock_list, mock_has, mock_count):
    """Callers that opt out of the listener check don't trigger the extra reads."""
    mock_list.return_value = []

    result = build_enrichment(
        "share-1",
        "viewer@x.com",
        viewer_listened_check=False,
    )

    mock_has.assert_not_called()
    mock_count.assert_not_called()
    assert result["viewerHasListened"] is False
    assert result["listenerCount"] == 0
