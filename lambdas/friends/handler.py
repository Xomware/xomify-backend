"""
XOMIFY Friends API Handler
================================
API endpoints for Friends

Endpoints:
- GET /friends/list - Get user's friends
- GET /friends/pending - Gets incoming and outgoing pending friend requets for a user
- GET /friends/profile - Gets Friends Profile
- GET /friends/all - Get all friends
- POST /friends/request - Request a friend
- POST /friends/aceept - accept a friend request
- POST /friends/reject - Reject a friend request
- DEL /friends/remove - Remove Friend
"""

import json
import asyncio
from lambdas.common.constants import FRIENDSHIPS_TABLE_NAME
from lambdas.common.logger import get_logger
from lambdas.common.utility_helpers import parse_body, require_fields
from lambdas.common.friendships_dynamo import list_all_friends_for_user, send_friend_request, accept_friend_request, delete_friends
from lambdas.common.dynamo_helpers import get_user_table_data, full_table_scan
from lambdas.common.friends_profile_helper import get_user_top_items


log = get_logger(__file__)


def handler(event, context):
    """
    Main Lambda handler for release radar.
    Routes to cron job or API endpoints.
    """
    try:
        
        # ========================================
        # API REQUESTS
        # ========================================
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method'))
        path = event.get('path', event.get('rawPath', ''))
        
        log.info(f"Release Radar API: {http_method} {path}")
        
        # Parse request
        query_params = event.get('queryStringParameters') or {}
        
        # Route request
        if 'list' in path and http_method == 'GET':
            require_fields(query_params, 'email')
            return list_friends(query_params)
        
        elif 'pending' in path and http_method == 'GET':
            require_fields(query_params, 'email')
            return get_pending_friends(query_params)
        
        elif 'profile' in path and http_method == 'GET':
            require_fields(query_params, 'friendEmail')
            return get_friends_profile(query_params)
        
        elif 'all' in path and http_method == 'GET':
            return get_all_friends()

        elif 'request' in path and http_method == 'POST':
            body = parse_body(event)
            require_fields(body, 'email', 'requestEmail')
            return request_friend(body)
        
        elif 'accept' in path and http_method == 'POST':
            body = parse_body(event)
            require_fields(body, 'email', 'requestEmail')
            return accept_friend(body)
        
        elif 'reject' in path and http_method == 'POST':
            body = parse_body(event)
            require_fields(body, 'email', 'requestEmail')
            return remove_friends(body)
        
        elif 'remove' in path and http_method == 'DEL':
            require_fields(query_params, 'email', 'friendEmail')
            return remove_friends(query_params)
        
        else:
            return response(404, {'error': 'Not found'})
            
    except Exception as err:
        log.error(f"Friends handler error: {err}")
        return response(500, {'error': str(err)})


# ============================================
#  GET /friends/list
#     Get user's friends   
#     Query params:
#        - email: User's email (required))
# ============================================

def list_friends(params: dict) -> dict:
    email = params.get('email')
    
    try:
        log.info(f"Listing all friends for user {email}")
        friends = list_all_friends_for_user(email)
        accepted = []
        blocked = []
        requested = []
        pending = []
        for friend in friends:
            if friend['status'] == 'accepted':
                accepted.append(friend)
            elif friend['status'] == 'pending':
                if friend['direction'] == 'outgoing':
                    requested.append(friend)
                else:
                    pending.append(friend)
            else:
                blocked.append(friend)

        log.info(f"Found {len(friends)} for user {email}")
        return response(200, {
            'email': email,
            'totalCount': len(friends),
            'accepted': accepted,
            'requested': requested,
            'pending': pending,
            'blocked': blocked,
            'acceptedCount': len(accepted),
            'requestedCount': len(requested),
            'pendingCount': len(pending),
            'blockedCount': len(blocked)
        })
        
    except Exception as err:
        log.error(f"List Friends error: {err}")
        return response(500, {'error': str(err)})

# ============================================
#  GET /friends/pending
#     Get user's pending friends   
#     Query params:
#        - email: User's email (required))
# ============================================

def get_pending_friends(params: dict) -> dict:
    email = params.get('email')
    
    try:
        log.info(f"Getting all pending friends for user {email}")
        friends = list_all_friends_for_user(email)
        pending = []
        for friend in friends:
            if friend['status'] == 'pending':
                pending.append(friend)
        
        return response(200, {
            'email': email,
            'pendingCount': len(pending),
            'pending': pending,
        })
        
    except Exception as err:
        log.error(f"Get Pending Friends error: {err}")
        return response(500, {'error': str(err)})

# ============================================
#  GET /friends/profile
#     Get a friends profile
#     Query params:
#        - friendEmail: Friends's email (required))
# ============================================

def get_friends_profile(params: dict) -> dict:
    friend_email = params.get('friendEmail')

    try:
        log.info(f"Getting friend's profile for user {friend_email}")
        friend_user = get_user_table_data(params['friendEmail'])
        log.info(f"Retrieved data for {params['friendEmail']}")
        friend_top_items = asyncio.run(get_user_top_items(friend_user))

        return response(200, {
            'displayName': friend_user.get('displayName', None),
            'email': friend_email,
            'userId': friend_user.get('userId', None),
            'topSongs': friend_top_items['tracks'],
            'topArtists': friend_top_items['artists'],
            'topGenres': friend_top_items['genres'],
            'avatar': friend_user.get('avatar', None)
        })

    except Exception as err:
        log.error(f"Get Friends Profile error: {err}")
        return response(500, {'error': str(err)})
    
# ============================================
#  GET /friends/all
#     Get all friends from friendhsip table
#     Query params:
#        - friendEmail: Friends's email (required))
# ============================================

def get_all_friends() -> dict:

    try:
        log.info("Getting All Friends from table.")
        friends = full_table_scan(FRIENDSHIPS_TABLE_NAME)
        
        return response(200, { 
            'friends': friends,
            'totalFriends': len(friends)
        })
        
    except Exception as err:
        log.error(f"Get Friends Profile error: {err}")
        return response(500, {'error': str(err)})

# ============================================
#  POST /friends/requset
#     Request a friend
#     Body:
#        - email: users's email (required))
#        - requestEmail: friend's email you are requesting(required))
# ============================================

def request_friend(body: dict) -> dict:
    email = body.get('email')
    request_email = body.get('requestEmail')

    try:
        log.info(f"User {email} is sending request to {request_email} to be a friend.")
        success = send_friend_request(email, request_email)
        log.info(f"Friend Request {'Success!' if success else 'Failure!'}")
        
        return response(200, { 
            'success': success
        })
        
    except Exception as err:
        log.error(f"Request Friend error: {err}")
        return response(500, {'error': str(err)})

# ============================================
#  POST /friends/accept
#     Accept a friend request
#     Body:
#        - email: users's email (required))
#        - requestEmail: friend's email you are accepting(required))
# ============================================

def accept_friend(body: dict) -> dict:
    email = body.get('email')
    request_email = body.get('requestEmail')

    try:
        log.info(f"User {email} is accepting friend request from {request_email}.")
        success = accept_friend_request(email, request_email)
        log.info(f"Friend Request Accepted {'Success!' if success else 'Failure!'}")
        
        return response(200, { 
            'success': success
        })
        
    except Exception as err:
        log.error(f"Accept Friend error: {err}")
        return response(500, {'error': str(err)})
    
# ============================================
#  POST /friends/reject
#     Reject a friend request
#     Body:
#        - email: users's email (required))
#        - requestEmail: friend's email you are rejecting(required))
# ============================================

def remove_friends(body: dict) -> dict:
    email = body.get('email')
    request_email = body.get('requestEmail')

    try:
        log.info(f"User {email} is rejecting friend request from {request_email}.")
        success = delete_friends(email, request_email)
        log.info(f"Friends Rejected {'Success!' if success else 'Failure!'}")
        
        return response(200, { 
            'success': success
        })
        
    except Exception as err:
        log.error(f"Reject Friend error: {err}")
        return response(500, {'error': str(err)})

# ============================================
# Response Helper
# ============================================

def response(status_code: int, body: dict) -> dict:
    """Build API Gateway response."""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,Authorization',
            'Access-Control-Allow-Methods': 'GET,OPTIONS'
        },
        'body': json.dumps(body, default=str)
    }