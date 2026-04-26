"""
XOMIFY Utility Helpers
======================
Common utilities for Lambda handlers.
"""

import json
import decimal
import base64
from datetime import datetime, timezone
from typing import Any, Optional, Set

from lambdas.common.logger import get_logger

log = get_logger(__file__)


# ============================================
# JSON Encoding
# ============================================

class XomifyJSONEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that handles:
    - Decimal (from DynamoDB)
    - datetime objects
    - sets
    """
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            # Convert to int if whole number, else float
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, set):
            return list(obj)
        return super().default(obj)


def json_dumps(obj: Any) -> str:
    """Serialize object to JSON string with custom encoder."""
    return json.dumps(obj, cls=XomifyJSONEncoder)


# ============================================
# Request Parsing
# ============================================

def is_api_request(event: dict) -> bool:
    """Check if the event is from API Gateway."""
    return isinstance(event.get('body'), str)


def is_cron_event(event: dict) -> bool:
    """Check if the event is from CloudWatch Events (cron)."""
    return event.get('source') == 'aws.events'


def parse_body(event: dict) -> dict:
    """
    Parse the request body from an event.
    Handles both API Gateway (string) and direct invocation (dict).
    """
    body = event.get('body')
    
    if body is None:
        return {}
    
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            log.warning("Failed to parse body as JSON")
            return {}
    
    return body if isinstance(body, dict) else {}


def get_query_params(event: dict) -> dict:
    """Get query string parameters from event."""
    return event.get('queryStringParameters') or {}


def get_path_params(event: dict) -> dict:
    """Get path parameters from event."""
    return event.get('pathParameters') or {}


# ============================================
# Response Building
# ============================================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Content-Type": "application/json"
}


def success_response(body: Any, status_code: int = 200, is_api: bool = True) -> dict:
    """
    Build a successful Lambda response.
    
    Args:
        body: Response data (will be JSON encoded if is_api=True)
        status_code: HTTP status code (default 200)
        is_api: If True, JSON encode the body
        
    Returns:
        Lambda response dict
    """
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json_dumps(body) if is_api else body,
        "isBase64Encoded": False
    }


def error_response(
    message: str, 
    status_code: int = 500, 
    is_api: bool = True,
    details: Optional[dict] = None
) -> dict:
    """
    Build an error Lambda response.
    
    Args:
        message: Error message
        status_code: HTTP status code (default 500)
        is_api: If True, JSON encode the body
        details: Optional additional error details
        
    Returns:
        Lambda response dict
    """
    body = {
        "error": {
            "message": message,
            "status": status_code,
            **(details or {})
        }
    }
    
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json_dumps(body) if is_api else body,
        "isBase64Encoded": False
    }


# ============================================
# Input Validation
# ============================================

def validate_input(
    data: Optional[dict], 
    required_fields: Set[str] = None, 
    optional_fields: Set[str] = None
) -> tuple[bool, Optional[str]]:
    """
    Validate input data has required fields and no extra fields.
    
    Args:
        data: Input dictionary to validate
        required_fields: Set of required field names
        optional_fields: Set of optional field names
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    required_fields = required_fields or set()
    optional_fields = optional_fields or set()
    
    if data is None:
        if required_fields:
            return False, f"Missing required fields: {required_fields}"
        return True, None
    
    if not isinstance(data, dict):
        return False, "Input must be a dictionary"
    
    data_keys = set(data.keys())
    allowed_keys = required_fields | optional_fields
    
    # Check for missing required fields
    missing = required_fields - data_keys
    if missing:
        return False, f"Missing required fields: {missing}"
    
    # Check for extra fields (if optional_fields is specified)
    if optional_fields:
        extra = data_keys - allowed_keys
        if extra:
            return False, f"Unexpected fields: {extra}"
    
    return True, None


def require_fields(data: dict, *fields: str) -> None:
    """
    Raise ValidationError if any required fields are missing.

    Usage:
        require_fields(body, 'email', 'userId')
    """
    from lambdas.common.errors import ValidationError

    missing = [f for f in fields if f not in data or data[f] is None]
    if missing:
        raise ValidationError(
            message=f"Missing required fields: {', '.join(missing)}",
            field=missing[0]
        )


# ============================================
# Caller Identity Resolution
# ============================================
# These helpers exist to bridge the migration window introduced by Track 0
# of the auth-identity epic. During the window:
#   * New per-user JWTs populate `requestContext.authorizer.{email,userId}`.
#   * Legacy static-token clients still send `email`/`userId` in the query
#     string or body.
# Once the fallback rate drops below the burn-in threshold (Q5 in the epic
# plan), Track 1l strips the fallback path entirely.

def _get_header_case_insensitive(event: dict, name: str) -> Optional[str]:
    """Return a header value from the event, matching the name case-insensitively."""
    headers = event.get("headers") or {}
    if not isinstance(headers, dict):
        return None
    target = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == target:
            return value if isinstance(value, str) else None
    return None


def _resolve_caller_identity(event: dict, field: str) -> str:
    """
    Resolve a caller-identity field from (in order): authorizer context,
    query string, then body. Raises MissingCallerIdentityError if absent
    in all three places.

    Args:
        event: Lambda event dict (API Gateway shape).
        field: Either 'email' or 'userId'.

    Returns:
        The resolved value as a string.
    """
    from lambdas.common.errors import MissingCallerIdentityError

    # 1. Trusted: authorizer context (populated by per-user JWTs).
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") if isinstance(request_context, dict) else None
    if isinstance(authorizer, dict):
        ctx_value = authorizer.get(field)
        if isinstance(ctx_value, str) and ctx_value:
            log.debug(f"caller_identity field={field} auth_path=context")
            return ctx_value

    # 2. Fallback: query string.
    query_params = get_query_params(event)
    qs_value = query_params.get(field) if isinstance(query_params, dict) else None
    if isinstance(qs_value, str) and qs_value:
        user_agent = _get_header_case_insensitive(event, "User-Agent") or "unknown"
        log.warning(
            f"caller_identity field={field} auth_path=fallback source=query user_agent={user_agent}"
        )
        return qs_value

    # 3. Fallback: body (only if it parses as JSON dict).
    body = parse_body(event)
    body_value = body.get(field) if isinstance(body, dict) else None
    if isinstance(body_value, str) and body_value:
        user_agent = _get_header_case_insensitive(event, "User-Agent") or "unknown"
        log.warning(
            f"caller_identity field={field} auth_path=fallback source=body user_agent={user_agent}"
        )
        return body_value

    # 4. Nothing — structured 401.
    raise MissingCallerIdentityError(field=field)


def get_caller_email(event: dict) -> str:
    """
    Resolve the caller's email.

    Trusts `event.requestContext.authorizer.email` first. Falls back to
    `queryStringParameters.email`, then JSON body `email`, during the Track 0
    -> Track 1 migration window. Raises `MissingCallerIdentityError` (HTTP 401)
    if no source provides a value.

    The fallback path emits a WARN log; CloudWatch counts gate the Track 1l
    cleanup that removes the fallback entirely (epic Q5).
    """
    return _resolve_caller_identity(event, "email")


def get_caller_user_id(event: dict) -> str:
    """
    Resolve the caller's Spotify user id.

    Trusts `event.requestContext.authorizer.userId` first. Falls back to
    `queryStringParameters.userId`, then JSON body `userId`, during the
    Track 0 -> Track 1 migration window. Raises `MissingCallerIdentityError`
    (HTTP 401) if no source provides a value.
    """
    return _resolve_caller_identity(event, "userId")


# ============================================
# Date/Time Utilities
# ============================================

def get_timestamp() -> str:
    """Get current UTC timestamp in standard format."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def get_iso_timestamp() -> str:
    """Get current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat() + 'Z'


def format_date(raw_date: str) -> datetime:
    """Parse MM/DD/YYYY date string to datetime."""
    parts = raw_date.split('/')
    return datetime(int(parts[2]), int(parts[0]), int(parts[1]))


# ============================================
# Encoding Utilities
# ============================================

def encode_credentials(key: str, secret: str) -> str:
    """Base64 encode credentials for Basic Auth."""
    data = f"{key}:{secret}"
    return base64.b64encode(data.encode('utf-8')).decode('utf-8')


# ============================================
# Backward Compatibility
# ============================================
# These match your old function names

DecimalEncoder = XomifyJSONEncoder

def is_called_from_api(event):
    return is_api_request(event)

def extract_body_from_event(event, is_api):
    return parse_body(event)

def build_successful_handler_response(body_object, is_api):
    return success_response(body_object, is_api=is_api)

def build_error_handler_response(error, is_api=True):
    """Handle old-style error string format."""
    if isinstance(error, str):
        try:
            error_dict = json.loads(error)
            status = error_dict.get('status', 500)
            message = error_dict.get('message', str(error))
        except json.JSONDecodeError:
            status = 500
            message = str(error)
    else:
        status = 500
        message = str(error)
    
    return error_response(message, status_code=status, is_api=is_api)

def set_response(statusCode, body):
    return success_response(body, status_code=statusCode or 500)

def validate_input_legacy(input_data, required_fields={}, optional_fields={}):
    """Legacy validate_input for backward compatibility."""
    is_valid, _ = validate_input(input_data, set(required_fields), set(optional_fields))
    return is_valid
