"""
Tests for shares_detail lambda.

Covers:
- happy path (share + interactions + friendRatings are wired together)
- missing share -> 404
- missing required fields -> 400
- interactions dedupe on (email, action)
- friendRatings filtered to the viewer's accepted friends + the author
- enrichment failures do not drop the share
"""

from unittest.mock import patch
import json

from lambdas.shares_detail.handler import handler


def _event(api_gateway_event, params):
    return {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/shares/detail",
        "queryStringParameters": params,
    }


def _share():
    return {
        "shareId": "share-1",
        "email": "alice@example.com",          # author
        "trackId": "spotify:track:1",
        "trackUri": "spotify:track:1",
        "trackName": "Bohemian Rhapsody",
        "artistName": "Queen",
        "albumName": "A Night at the Opera",
        "albumArtUrl": "https://img.example.com/boh.jpg",
        "createdAt": "2026-04-20T12:00:00+00:00",
        "sharedAt": "2026-04-20T12:00:00+00:00",
    }


@patch('lambdas.shares_detail.handler.batch_get_users')
@patch('lambdas.shares_detail.handler.list_all_track_ratings_for_user')
@patch('lambdas.shares_detail.handler.list_all_friends_for_user')
@patch('lambdas.shares_detail.handler.list_reactions_for_share')
@patch('lambdas.shares_detail.handler.build_enrichment')
@patch('lambdas.shares_detail.handler.get_share')
def test_shares_detail_happy_path(
    mock_get_share,
    mock_enrich,
    mock_reactions,
    mock_friends,
    mock_ratings,
    mock_batch_users,
    mock_context,
    api_gateway_event,
):
    mock_get_share.return_value = _share()
    mock_enrich.return_value = {
        "queuedCount": 2,
        "ratedCount": 2,
        "viewerHasQueued": True,
        "viewerRating": 4.5,
        "sharerRating": 5.0,
    }
    # 2 reactions -> should produce interactions for each (viewer queued,
    # bob queued + rated).
    mock_reactions.return_value = [
        {
            "shareId": "share-1", "email": "bob@example.com",
            "queued": True, "rated": True, "rating": 4.0,
            "queuedAt": "2026-04-21T09:00:00+00:00",
            "ratedAt":  "2026-04-21T09:05:00+00:00",
            "updatedAt":"2026-04-21T09:05:00+00:00",
            "createdAt":"2026-04-21T09:00:00+00:00",
            "sharedBy": "alice@example.com",
        },
        {
            "shareId": "share-1", "email": "viewer@example.com",
            "queued": True, "rated": True, "rating": 4.5,
            "queuedAt": "2026-04-21T10:00:00+00:00",
            "ratedAt":  "2026-04-21T10:05:00+00:00",
            "sharedBy": "alice@example.com",
        },
    ]
    # viewer has 2 accepted friends (bob + carol) and 1 blocked (should
    # be filtered out).
    mock_friends.return_value = [
        {"friendEmail": "bob@example.com",   "status": "accepted"},
        {"friendEmail": "carol@example.com", "status": "accepted"},
        {"friendEmail": "eve@example.com",   "status": "blocked"},
    ]

    def _ratings_for(email):
        # Only bob and carol (friends) + alice (author) should be queried.
        if email == "bob@example.com":
            return [
                {"email": email, "trackId": "spotify:track:1", "rating": 4.0,
                 "ratedAt": "2026-04-21 09:05:00"},
                {"email": email, "trackId": "spotify:track:OTHER", "rating": 3.0,
                 "ratedAt": "2026-04-18 09:00:00"},
            ]
        if email == "carol@example.com":
            return [
                {"email": email, "trackId": "spotify:track:1", "rating": 5.0,
                 "ratedAt": "2026-04-22 00:00:00"},
            ]
        if email == "alice@example.com":
            # author's own rating — surfaces alongside friend ratings.
            return [
                {"email": email, "trackId": "spotify:track:1", "rating": 5.0,
                 "ratedAt": "2026-04-20 12:00:00"},
            ]
        return []

    mock_ratings.side_effect = _ratings_for
    mock_batch_users.return_value = {
        "alice@example.com": {"email": "alice@example.com", "displayName": "Alice",  "avatar": "a.jpg"},
        "bob@example.com":   {"email": "bob@example.com",   "displayName": "Bob",    "avatar": "b.jpg"},
        "carol@example.com": {"email": "carol@example.com", "displayName": "Carol",  "avatar": "c.jpg"},
        "viewer@example.com":{"email": "viewer@example.com","displayName": "Viewer", "avatar": "v.jpg"},
    }

    response = handler(
        _event(api_gateway_event, {"email": "viewer@example.com", "shareId": "share-1"}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])

    # ----- share (with enrichment merged)
    share = body['share']
    assert share['shareId'] == 'share-1'
    assert share['trackName'] == 'Bohemian Rhapsody'
    assert share['queuedCount'] == 2
    assert share['ratedCount'] == 2
    assert share['viewerRating'] == 4.5
    assert share['sharerRating'] == 5.0
    assert share['viewerHasQueued'] is True

    # ----- interactions: bob queued, bob rated, viewer queued, viewer rated = 4 rows
    interactions = body['interactions']
    assert len(interactions) == 4
    actions_by_email = {(i['email'], i['action']) for i in interactions}
    assert ('bob@example.com', 'queued') in actions_by_email
    assert ('bob@example.com', 'rated') in actions_by_email
    assert ('viewer@example.com', 'queued') in actions_by_email
    assert ('viewer@example.com', 'rated') in actions_by_email
    # displayName + avatar hydrated
    bob_q = next(i for i in interactions if i['email'] == 'bob@example.com' and i['action'] == 'queued')
    assert bob_q['displayName'] == 'Bob'
    assert bob_q['avatar'] == 'b.jpg'

    # ----- friendRatings: bob (friend) + carol (friend) + alice (author)
    friend_ratings = body['friendRatings']
    rating_emails = {r['email'] for r in friend_ratings}
    assert rating_emails == {"bob@example.com", "carol@example.com", "alice@example.com"}
    # filtered to this trackId only (no spotify:track:OTHER leak)
    assert all(r.get('rating') is not None for r in friend_ratings)
    # author hydrated
    alice_rating = next(r for r in friend_ratings if r['email'] == 'alice@example.com')
    assert alice_rating['displayName'] == 'Alice'

    # ratings for non-friends should NOT have been requested — only bob, carol, alice
    called_emails = {call.args[0] for call in mock_ratings.call_args_list}
    assert called_emails == {"bob@example.com", "carol@example.com", "alice@example.com"}


@patch('lambdas.shares_detail.handler.get_share')
def test_shares_detail_missing_share_returns_404(
    mock_get_share, mock_context, api_gateway_event
):
    mock_get_share.return_value = None
    response = handler(
        _event(api_gateway_event, {"email": "viewer@example.com", "shareId": "missing"}),
        mock_context,
    )
    assert response['statusCode'] == 404


@patch('lambdas.shares_detail.handler.get_share')
def test_shares_detail_missing_required_fields_returns_400(
    mock_get_share, mock_context, api_gateway_event
):
    response = handler(_event(api_gateway_event, {"email": "viewer@example.com"}), mock_context)
    assert response['statusCode'] == 400
    mock_get_share.assert_not_called()


@patch('lambdas.shares_detail.handler.batch_get_users')
@patch('lambdas.shares_detail.handler.list_all_track_ratings_for_user')
@patch('lambdas.shares_detail.handler.list_all_friends_for_user')
@patch('lambdas.shares_detail.handler.list_reactions_for_share')
@patch('lambdas.shares_detail.handler.build_enrichment')
@patch('lambdas.shares_detail.handler.get_share')
def test_shares_detail_interactions_dedupe_by_email_action(
    mock_get_share, mock_enrich, mock_reactions, mock_friends, mock_ratings, mock_batch_users,
    mock_context, api_gateway_event,
):
    """Single row with queued=True rated=True -> two events, not one merged."""
    mock_get_share.return_value = _share()
    mock_enrich.return_value = {}
    mock_reactions.return_value = [
        {
            "shareId": "share-1", "email": "bob@example.com",
            "queued": True, "rated": True, "rating": 4.0,
            "queuedAt": "2026-04-21T09:00:00+00:00",
            "ratedAt":  "2026-04-21T09:05:00+00:00",
        },
    ]
    mock_friends.return_value = []
    mock_ratings.return_value = []
    mock_batch_users.return_value = {}

    response = handler(
        _event(api_gateway_event, {"email": "viewer@example.com", "shareId": "share-1"}),
        mock_context,
    )
    body = json.loads(response['body'])
    # One queued + one rated for the same email, no collapsing.
    actions = [(i['email'], i['action']) for i in body['interactions']]
    assert ('bob@example.com', 'queued') in actions
    assert ('bob@example.com', 'rated') in actions
    assert len(actions) == 2


@patch('lambdas.shares_detail.handler.batch_get_users')
@patch('lambdas.shares_detail.handler.list_all_track_ratings_for_user')
@patch('lambdas.shares_detail.handler.list_all_friends_for_user')
@patch('lambdas.shares_detail.handler.list_reactions_for_share')
@patch('lambdas.shares_detail.handler.build_enrichment')
@patch('lambdas.shares_detail.handler.get_share')
def test_shares_detail_friend_ratings_scoped_to_accepted_friends_only(
    mock_get_share, mock_enrich, mock_reactions, mock_friends, mock_ratings, mock_batch_users,
    mock_context, api_gateway_event,
):
    """Pending / blocked friends must NOT appear in friendRatings."""
    mock_get_share.return_value = _share()
    mock_enrich.return_value = {}
    mock_reactions.return_value = []
    mock_friends.return_value = [
        {"friendEmail": "bob@example.com",     "status": "accepted"},
        {"friendEmail": "carol@example.com",   "status": "pending"},
        {"friendEmail": "eve@example.com",     "status": "blocked"},
    ]
    mock_ratings.side_effect = lambda email: (
        [{"email": email, "trackId": "spotify:track:1", "rating": 4.0,
          "ratedAt": "2026-04-21 09:00:00"}]
        if email in {"bob@example.com", "alice@example.com"} else []
    )
    mock_batch_users.return_value = {}

    response = handler(
        _event(api_gateway_event, {"email": "viewer@example.com", "shareId": "share-1"}),
        mock_context,
    )
    body = json.loads(response['body'])
    emails = {r['email'] for r in body['friendRatings']}
    # bob (friend) + alice (author). Carol (pending) and Eve (blocked) must be absent.
    assert emails == {"bob@example.com", "alice@example.com"}
    # Ratings lookup was restricted to accepted friends + author.
    called_emails = {call.args[0] for call in mock_ratings.call_args_list}
    assert "carol@example.com" not in called_emails
    assert "eve@example.com" not in called_emails


@patch('lambdas.shares_detail.handler.batch_get_users')
@patch('lambdas.shares_detail.handler.list_all_track_ratings_for_user')
@patch('lambdas.shares_detail.handler.list_all_friends_for_user')
@patch('lambdas.shares_detail.handler.list_reactions_for_share')
@patch('lambdas.shares_detail.handler.build_enrichment')
@patch('lambdas.shares_detail.handler.get_share')
def test_shares_detail_enrichment_failure_is_non_fatal(
    mock_get_share, mock_enrich, mock_reactions, mock_friends, mock_ratings, mock_batch_users,
    mock_context, api_gateway_event,
):
    """If build_enrichment explodes, the share still comes back with defaults."""
    mock_get_share.return_value = _share()
    mock_enrich.side_effect = RuntimeError("interactions table unreachable")
    mock_reactions.return_value = []
    mock_friends.return_value = []
    mock_ratings.return_value = []
    mock_batch_users.return_value = {}

    response = handler(
        _event(api_gateway_event, {"email": "viewer@example.com", "shareId": "share-1"}),
        mock_context,
    )

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['share']['shareId'] == 'share-1'
    assert body['share']['queuedCount'] == 0
    assert body['share']['viewerHasQueued'] is False
