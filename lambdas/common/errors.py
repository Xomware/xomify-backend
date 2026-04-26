"""
XOMIFY Error Classes
====================
Standardized error handling for all Lambda functions.

Features:
- Consistent error response format
- HTTP status codes
- Easy to catch and handle
- Serializable for API responses
"""

import json
import traceback
from typing import Optional
from lambdas.common.logger import get_logger

log = get_logger(__file__)


class XomifyError(Exception):
    """
    Base exception class for all Xomify errors.
    
    Usage:
        raise XomifyError("Something went wrong", status=400)
        
    Or catch and convert to response:
        except XomifyError as e:
            return e.to_response()
    """
    
    def __init__(
        self, 
        message: str, 
        handler: str = "unknown",
        function: str = "unknown", 
        status: int = 500,
        details: Optional[dict] = None
    ):
        self.message = message
        self.handler = handler
        self.function = function
        self.status = status
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> dict:
        """Convert error to dictionary for JSON response."""
        return {
            "error": {
                "message": self.message,
                "handler": self.handler,
                "function": self.function,
                "status": self.status,
                **self.details
            }
        }
    
    def to_response(self, is_api: bool = True) -> dict:
        """Convert error to Lambda response format."""
        body = self.to_dict()
        return {
            "statusCode": self.status,
            "headers": {
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json"
            },
            "body": json.dumps(body) if is_api else body,
            "isBase64Encoded": False
        }
    
    def log_error(self):
        """Log the error with full context."""
        log.error(f"💥 {self.__class__.__name__} in {self.handler}.{self.function}: {self.message}")
        if self.details:
            log.error(f"   Details: {self.details}")
    
    def __str__(self) -> str:
        return json.dumps(self.to_dict())


# ============================================
# Specific Error Types
# ============================================

class AuthorizationError(XomifyError):
    """Raised when authorization fails."""

    def __init__(self, message: str = "Unauthorized", handler: str = "authorizer", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=401
        )


class MissingCallerIdentityError(AuthorizationError):
    """
    Raised when caller identity (email/userId) cannot be resolved from either
    the authorizer context or the request fallback (query/body).

    Maps to HTTP 401 — the caller is unauthenticated for the purposes of
    this endpoint because we have no way to know who they are.
    """

    def __init__(
        self,
        field: str,
        handler: str = "utility_helpers",
        function: str = "unknown",
    ):
        message = f"Missing caller identity: '{field}' not present in authorizer context, query string, or body"
        super().__init__(
            message=message,
            handler=handler,
            function=function,
        )
        self.details = {"field": field}


class ValidationError(XomifyError):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, handler: str = "unknown", function: str = "unknown", field: str = None):
        details = {"field": field} if field else {}
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=400,
            details=details
        )


class NotFoundError(XomifyError):
    """Raised when a resource is not found."""
    
    def __init__(self, message: str, handler: str = "unknown", function: str = "unknown", resource: str = None):
        details = {"resource": resource} if resource else {}
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=404,
            details=details
        )


class DynamoDBError(XomifyError):
    """Raised when DynamoDB operations fail."""
    
    def __init__(self, message: str, handler: str = "dynamo_helpers", function: str = "unknown", table: str = None):
        details = {"table": table} if table else {}
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500,
            details=details
        )


class SpotifyAPIError(XomifyError):
    """Raised when Spotify API calls fail."""
    
    def __init__(self, message: str, handler: str = "spotify", function: str = "unknown", endpoint: str = None):
        details = {"endpoint": endpoint} if endpoint else {}
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=502,
            details=details
        )


class WrappedError(XomifyError):
    """Raised when wrapped processing fails."""
    
    def __init__(self, message: str, handler: str = "wrapped", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500
        )

class ReleaseRadarEmailError(XomifyError):
    """Raised when release radar email processing fails."""

    def __init__(self, message: str, handler: str = "release_radar_email", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500
        )
class ReleaseRadarError(XomifyError):
    """Raised when release radar processing fails."""
    
    def __init__(self, message: str, handler: str = "release_radar", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500
        )


class WrappedEmailError(XomifyError):
    """Raised when email sending fails."""
    
    def __init__(self, message: str, handler: str = "wrapped_email", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500
        )


class UserTableError(XomifyError):
    """Raised when user table operations fail."""

    def __init__(self, message: str, handler: str = "user", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500
        )


class ApnsError(XomifyError):
    """Raised when APNs HTTP/2 delivery or JWT signing fails."""

    def __init__(
        self,
        message: str,
        handler: str = "apns_client",
        function: str = "unknown",
        status_code: int | None = None,
        reason: str | None = None,
    ):
        details: dict = {}
        if status_code is not None:
            details["apnsStatusCode"] = status_code
        if reason is not None:
            details["apnsReason"] = reason
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=502,
            details=details,
        )


class NotificationsError(XomifyError):
    """Raised when notification dispatch fails."""

    def __init__(self, message: str, handler: str = "notifications", function: str = "unknown"):
        super().__init__(
            message=message,
            handler=handler,
            function=function,
            status=500,
        )


# ============================================
# Sensitive Data Masking
# ============================================

# Fields that should be masked in logs
SENSITIVE_FIELDS = {
    'refreshToken', 'refresh_token',
    'accessToken', 'access_token',
    'password', 'passwd',
    'secret', 'apiKey', 'api_key',
    'authorization', 'Authorization',
    'x-api-key', 'X-API-Key',
    'sessionToken', 'session_token',
    'privateKey', 'private_key',
    'clientSecret', 'client_secret'
}

def mask_sensitive_data(data, mask_value="***MASKED***"):
    """
    Recursively mask sensitive fields in dictionaries and lists.

    Args:
        data: Dict, list, or other data structure
        mask_value: String to replace sensitive values with

    Returns:
        Masked copy of data
    """
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            # Check if key is sensitive
            if key in SENSITIVE_FIELDS or any(sensitive.lower() in key.lower() for sensitive in ['token', 'password', 'secret', 'key', 'auth']):
                masked[key] = mask_value
            else:
                masked[key] = mask_sensitive_data(value, mask_value)
        return masked
    elif isinstance(data, list):
        return [mask_sensitive_data(item, mask_value) for item in data]
    elif isinstance(data, str) and len(data) > 100:
        # Truncate very long strings (might be encoded tokens)
        return data[:50] + "...[truncated]..." + data[-20:]
    else:
        return data


def log_error_context(handler_name: str, function_name: str, event: dict, context=None):
    """
    Log relevant context information when an error occurs.

    Args:
        handler_name: Name of the handler
        function_name: Name of the function
        event: Lambda event dict
        context: Lambda context object
    """
    try:
        # Extract useful info
        http_method = event.get('httpMethod', event.get('requestContext', {}).get('http', {}).get('method', 'N/A'))
        path = event.get('path', event.get('rawPath', 'N/A'))
        query_params = mask_sensitive_data(event.get('queryStringParameters', {}))
        headers = mask_sensitive_data(event.get('headers', {}))

        # Log context
        log.error(f"📋 Error Context for {handler_name}.{function_name}:")
        log.error(f"   Method: {http_method}")
        log.error(f"   Path: {path}")
        log.error(f"   Query Params: {query_params}")
        log.error(f"   Headers: {headers}")

        # Log body if present (masked)
        if event.get('body'):
            try:
                body = json.loads(event['body']) if isinstance(event['body'], str) else event['body']
                safe_body = mask_sensitive_data(body)
                log.error(f"   Body: {safe_body}")
            except:
                log.error(f"   Body: [Unable to parse]")

        # Log context info if available
        if context:
            log.error(f"   Request ID: {getattr(context, 'aws_request_id', 'N/A')}")
            log.error(f"   Function: {getattr(context, 'function_name', 'N/A')}")

    except Exception as log_error:
        # Don't let logging errors break error handling
        log.error(f"⚠️  Error while logging context: {log_error}")


# ============================================
# Error Handler Decorator
# ============================================

def handle_errors(handler_name: str, log_context: bool = True):
    """
    Decorator to handle errors consistently across handlers.

    Args:
        handler_name: Name of the handler for logging
        log_context: If True, logs event/context details on error (with sensitive data masked)

    Usage:
        @handle_errors("wrapped")
        def handler(event, context):
            ...

        # Disable context logging for performance
        @handle_errors("wrapped", log_context=False)
        def handler(event, context):
            ...
    """
    def decorator(func):
        def wrapper(event, context):
            try:
                return func(event, context)
            except XomifyError as e:
                # Log Xomify errors with context
                e.log_error()
                if log_context:
                    log_error_context(handler_name, func.__name__, event, context)
                return e.to_response()
            except Exception as e:
                # Catch unexpected errors
                log.error(f"💥 Unexpected error in {handler_name}: {str(e)}")
                log.error(traceback.format_exc())

                # Log context for unexpected errors
                if log_context:
                    log_error_context(handler_name, func.__name__, event, context)

                error = XomifyError(
                    message=str(e),
                    handler=handler_name,
                    function=func.__name__,
                    status=500
                )
                return error.to_response()
        return wrapper
    return decorator


# ============================================
# Backward Compatibility Aliases
# ============================================
# These match your old error class names

BaseXomifyException = XomifyError
LambdaAuthorizerError = AuthorizationError
UnauthorizedError = AuthorizationError
DynamodbError = DynamoDBError
WrappednError = WrappedError  # Note: fixing the typo from original
UpdateUserTableError = UserTableError
