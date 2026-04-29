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
