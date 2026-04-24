"""
Tests for groups_list lambda — ensures membership rows are hydrated
with full Group metadata before returning, so clients don't see
headless rows that fail to decode.
"""

import json
from unittest.mock import patch

from lambdas.groups_list.handler import handler


@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_hydrates_membership_with_group_metadata(
    mock_list_memberships, mock_batch_get, mock_context, api_gateway_event
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

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/groups/list",
        "queryStringParameters": {"email": "test@example.com"}
    }

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


@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_drops_memberships_with_missing_group(
    mock_list_memberships, mock_batch_get, mock_context, api_gateway_event
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

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/groups/list",
        "queryStringParameters": {"email": "test@example.com"}
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalGroups'] == 1
    assert body['groups'][0]['groupId'] == 'alive'


@patch('lambdas.groups_list.handler.batch_get_groups')
@patch('lambdas.groups_list.handler.list_groups_for_user')
def test_groups_list_empty(
    mock_list_memberships, mock_batch_get, mock_context, api_gateway_event
):
    mock_list_memberships.return_value = []
    mock_batch_get.return_value = []

    event = {
        **api_gateway_event,
        "httpMethod": "GET",
        "path": "/groups/list",
        "queryStringParameters": {"email": "test@example.com"}
    }

    response = handler(event, mock_context)

    assert response['statusCode'] == 200
    body = json.loads(response['body'])
    assert body['totalGroups'] == 0
    assert body['groups'] == []
