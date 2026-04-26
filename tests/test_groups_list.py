"""
Tests for groups_list lambda — ensures membership rows are hydrated
with full Group metadata before returning, so clients don't see
headless rows that fail to decode.

memberCount is always recomputed live from the membership GSI — the
cached attribute on the GROUPS row has historically drifted (old seed
set fresh 1-member groups to 2 until PR #136). The handler also issues
a best-effort write-back to heal the stored value.

Caller email is sourced from the authorizer context via `authorized_event`
(post Track 1 migration). The handler takes no other request fields.
"""

import json
from unittest.mock import patch

from lambdas.groups_list.handler import handler


def _event(authorized_event, email: str) -> dict:
    return authorized_event(
        email=email,
        httpMethod="GET",
        path="/groups/list",
    )


@patch('lambdas.groups_list.handler.update_group_member_count')
@patch('lambdas.groups_list.handler.list_members_of_group')
@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_hydrates_membership_with_group_metadata(
    mock_list_memberships, mock_batch_get, mock_list_members, mock_update_count,
    mock_context, authorized_event,
):
    """Membership rows get merged with the full Group item so `name`,
    `createdBy`, `memberCount` end up on the wire."""
    mock_list_memberships.return_value = [
        {"email": "test@example.com", "groupId": "g1", "role": "owner",  "joinedAt": "2026-01-01 00:00:00"},
        {"email": "test@example.com", "groupId": "g2", "role": "member", "joinedAt": "2026-02-01 00:00:00"}
    ]
    mock_batch_get.return_value = [
        {"groupId": "g1", "name": "Summer Tunes", "createdBy": "test@example.com", "memberCount": 4, "createdAt": "2026-01-01 00:00:00"},
        {"groupId": "g2", "name": "Road Trip",   "createdBy": "other@example.com", "memberCount": 7, "createdAt": "2026-01-10 00:00:00"}
    ]
    # Live membership matches cached counts -> no heal.
    mock_list_members.side_effect = lambda gid: (
        [{"email": f"u{i}@example.com"} for i in range(4)] if gid == 'g1'
        else [{"email": f"u{i}@example.com"} for i in range(7)]
    )

    event = _event(authorized_event, "test@example.com")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalGroups'] == 2
    assert len(body['groups']) == 2

    g1 = next(g for g in body['groups'] if g['groupId'] == 'g1')
    assert g1['name'] == 'Summer Tunes'
    assert g1['memberCount'] == 4
    assert g1['role'] == 'owner'
    assert g1['joinedAt'] == '2026-01-01 00:00:00'

    g2 = next(g for g in body['groups'] if g['groupId'] == 'g2')
    assert g2['name'] == 'Road Trip'
    assert g2['role'] == 'member'
    assert g2['memberCount'] == 7

    # Cached == live so no heal should fire.
    mock_update_count.assert_not_called()


@patch('lambdas.groups_list.handler.update_group_member_count')
@patch('lambdas.groups_list.handler.list_members_of_group')
@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_drops_memberships_with_missing_group(
    mock_list_memberships, mock_batch_get, mock_list_members, mock_update_count,
    mock_context, authorized_event,
):
    """If the Groups table no longer has a row for a membership's groupId
    (e.g. the group was deleted but the membership wasn't cleaned up), the
    stale membership is dropped rather than returning a headless row."""
    mock_list_memberships.return_value = [
        {"email": "test@example.com", "groupId": "alive",   "role": "member"},
        {"email": "test@example.com", "groupId": "deleted", "role": "member"}
    ]
    mock_batch_get.return_value = [
        {"groupId": "alive", "name": "Still Here", "createdBy": "owner@test.com", "memberCount": 2}
    ]
    mock_list_members.return_value = [
        {"email": "owner@test.com"},
        {"email": "test@example.com"},
    ]

    event = _event(authorized_event, "test@example.com")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalGroups'] == 1
    assert body['groups'][0]['groupId'] == 'alive'
    assert body['groups'][0]['memberCount'] == 2


@patch('lambdas.groups_list.handler.update_group_member_count')
@patch('lambdas.groups_list.handler.list_members_of_group')
@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_empty(
    mock_list_memberships, mock_batch_get, mock_list_members, mock_update_count,
    mock_context, authorized_event,
):
    mock_list_memberships.return_value = []
    mock_batch_get.return_value = []

    event = _event(authorized_event, "test@example.com")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalGroups'] == 0
    assert body['groups'] == []
    mock_list_members.assert_not_called()
    mock_update_count.assert_not_called()


@patch('lambdas.groups_list.handler.update_group_member_count')
@patch('lambdas.groups_list.handler.list_members_of_group')
@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_returns_live_member_count_when_cache_is_stale(
    mock_list_memberships, mock_batch_get, mock_list_members, mock_update_count,
    mock_context, authorized_event,
):
    """Regression test for the seed-bug leftover: cached memberCount=2 on a
    group that actually has 1 member. The response must carry the live count,
    and the handler should opportunistically heal the stored value."""
    mock_list_memberships.return_value = [
        {"email": "solo@example.com", "groupId": "stale", "role": "owner"},
    ]
    # Stale cached value — the bug that motivated this fix.
    mock_batch_get.return_value = [
        {"groupId": "stale", "name": "Just Me", "createdBy": "solo@example.com", "memberCount": 2}
    ]
    # GSI shows the group truly has one member.
    mock_list_members.return_value = [{"email": "solo@example.com"}]

    event = _event(authorized_event, "solo@example.com")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalGroups'] == 1
    assert body['groups'][0]['memberCount'] == 1, (
        "response must carry live count, not cached stale value"
    )
    # Heal fired exactly once with the corrected count.
    mock_update_count.assert_called_once_with("stale", 1)


@patch('lambdas.groups_list.handler.update_group_member_count')
@patch('lambdas.groups_list.handler.list_members_of_group')
@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_heal_failure_does_not_break_response(
    mock_list_memberships, mock_batch_get, mock_list_members, mock_update_count,
    mock_context, authorized_event,
):
    """A blow-up from the best-effort write-back must not fail the request."""
    mock_list_memberships.return_value = [
        {"email": "solo@example.com", "groupId": "stale", "role": "owner"},
    ]
    mock_batch_get.return_value = [
        {"groupId": "stale", "name": "Just Me", "createdBy": "solo@example.com", "memberCount": 2}
    ]
    mock_list_members.return_value = [{"email": "solo@example.com"}]
    mock_update_count.side_effect = RuntimeError("DynamoDB threw")

    event = _event(authorized_event, "solo@example.com")

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['groups'][0]['memberCount'] == 1


@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_missing_caller_identity_returns_401(
    mock_list_memberships, mock_context, legacy_event,
):
    """No authorizer context AND no caller email in query/body -> 401, no DDB reads."""
    event = legacy_event()  # no email / userId anywhere
    event["httpMethod"] = "GET"
    event["path"] = "/groups/list"

    response = handler(event, mock_context)

    assert response['statusCode'] == 401
    mock_list_memberships.assert_not_called()
