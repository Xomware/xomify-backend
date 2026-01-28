# Error Handling Guide

## Overview

The Xomify backend uses a standardized error handling system with automatic logging, sensitive data masking, and consistent error responses.

## Features

✅ **Automatic error logging** with full stack traces
✅ **Sensitive data masking** for tokens, passwords, keys
✅ **Context logging** - HTTP method, path, params, headers, body
✅ **Consistent error responses** across all endpoints
✅ **Custom error types** for different scenarios

## Basic Usage

### Using the Decorator

```python
from lambdas.common.errors import handle_errors

@handle_errors("my_handler")
def handler(event, context):
    # Your handler code
    if something_wrong:
        raise ValidationError("Invalid input", field="email")

    return success_response({"data": "success"})
```

### Error Types

#### XomifyError (Base)
Generic error, use for any error scenario:
```python
raise XomifyError("Something went wrong", handler="my_handler", status=500)
```

#### ValidationError (400)
For invalid input:
```python
raise ValidationError("Email is required", field="email")
```

#### NotFoundError (404)
For missing resources:
```python
raise NotFoundError("User not found", resource="user")
```

#### AuthorizationError (401)
For authentication failures:
```python
raise AuthorizationError("Invalid token")
```

#### DynamoDBError (500)
For database errors:
```python
raise DynamoDBError("Failed to query table", table="users")
```

#### SpotifyAPIError (502)
For Spotify API failures:
```python
raise SpotifyAPIError("Spotify API timeout", endpoint="/me/top/tracks")
```

## Sensitive Data Masking

### What Gets Masked?

The system automatically masks these fields in error logs:

- `refreshToken`, `accessToken`, `sessionToken`
- `password`, `passwd`
- `secret`, `apiKey`, `clientSecret`
- `authorization` headers
- Any field containing: `token`, `password`, `secret`, `key`, `auth`

### Example

**Original data:**
```python
{
    "email": "user@example.com",
    "refreshToken": "abc123_secret_token",
    "userId": "spotify123"
}
```

**Logged as:**
```python
{
    "email": "user@example.com",
    "refreshToken": "***MASKED***",
    "userId": "spotify123"
}
```

### Custom Masking

```python
from lambdas.common.errors import mask_sensitive_data

data = {"password": "secret123"}
masked = mask_sensitive_data(data, mask_value="[REDACTED]")
# Result: {"password": "[REDACTED]"}
```

## Error Context Logging

When an error occurs, the decorator automatically logs:

```
📋 Error Context for user_update.handler:
   Method: POST
   Path: /user/user-table
   Query Params: {}
   Headers: {"Content-Type": "application/json", "Authorization": "***MASKED***"}
   Body: {"email": "user@example.com", "refreshToken": "***MASKED***"}
   Request ID: abc-123-def
   Function: xomify-user-update
```

### Disable Context Logging

For performance-critical paths or when context isn't needed:

```python
@handle_errors("my_handler", log_context=False)
def handler(event, context):
    # Context won't be logged on error
    pass
```

## Complete Handler Example

```python
from lambdas.common.errors import handle_errors, ValidationError, NotFoundError
from lambdas.common.utility_helpers import success_response, parse_body, require_fields
from lambdas.common.logger import get_logger

log = get_logger(__file__)

HANDLER = 'user_update'

@handle_errors(HANDLER)
def handler(event, context):
    # Parse and validate
    body = parse_body(event)
    require_fields(body, 'email')

    email = body.get('email')

    # Business logic
    if not is_valid_email(email):
        raise ValidationError("Invalid email format", field="email")

    user = get_user(email)
    if not user:
        raise NotFoundError("User not found", resource="user")

    # Success
    log.info(f"Updated user {email}")
    return success_response({"updated": True})
```

## Error Response Format

All errors return this structure:

```json
{
    "statusCode": 400,
    "headers": {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*"
    },
    "body": {
        "error": {
            "message": "Email is required",
            "handler": "user_update",
            "function": "handler",
            "status": 400,
            "field": "email"
        }
    }
}
```

## Testing Error Handling

```python
import pytest
from lambdas.common.errors import ValidationError

def test_validation_error():
    with pytest.raises(ValidationError) as exc_info:
        raise ValidationError("Invalid input", field="email")

    assert exc_info.value.status == 400
    assert exc_info.value.details["field"] == "email"
```

## Best Practices

### DO ✅

- Use specific error types (`ValidationError`, `NotFoundError`, etc.)
- Include context in error messages
- Let the decorator handle error responses
- Log important events before potential errors
- Use `require_fields()` for input validation

### DON'T ❌

- Don't log sensitive data directly (use the masking function)
- Don't catch exceptions without re-raising or handling
- Don't return raw error messages to users
- Don't use generic `Exception` when specific error types exist
- Don't log passwords, tokens, or API keys

## CloudWatch Logs

Error logs will appear in CloudWatch with this structure:

```
ERROR: 💥 Unexpected error in user_update: Validation failed
ERROR: <full stack trace>
ERROR: 📋 Error Context for user_update.handler:
ERROR:    Method: POST
ERROR:    Path: /user/user-table
ERROR:    Query Params: {}
ERROR:    Headers: {<masked headers>}
ERROR:    Body: {<masked body>}
```

Use CloudWatch Insights to search for errors:

```sql
fields @timestamp, @message
| filter @message like /💥 Unexpected error/
| sort @timestamp desc
| limit 50
```

## Migration from Old Error Handling

Old code:
```python
try:
    # do something
except Exception as err:
    log.error(f"Error: {err}")
    return {
        'statusCode': 500,
        'body': json.dumps({'error': str(err)})
    }
```

New code:
```python
@handle_errors("my_handler")
def handler(event, context):
    # do something
    # Decorator handles all errors automatically
    return success_response({"data": "success"})
```

## Adding Custom Error Types

```python
from lambdas.common.errors import XomifyError

class CustomError(XomifyError):
    """Custom error for specific use case"""

    def __init__(self, message: str, custom_field: str = None):
        super().__init__(
            message=message,
            handler="custom",
            function="custom_func",
            status=422,  # Custom status code
            details={"customField": custom_field}
        )
```
