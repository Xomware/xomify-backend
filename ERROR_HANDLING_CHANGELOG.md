# Error Handling Enhancement - Changelog

## Summary

Enhanced the `@handle_errors` decorator to automatically log request context on failures with sensitive data masking.

## What Changed

### ✅ New Features

1. **Automatic Context Logging on Errors**
   - HTTP method, path, query params
   - Request headers and body
   - AWS request ID and function name
   - All logged automatically when errors occur

2. **Sensitive Data Masking**
   - Automatically masks tokens, passwords, secrets, API keys
   - Pattern-based detection (any field containing 'token', 'password', etc.)
   - Truncates long strings (potential encoded tokens)
   - Customizable mask value

3. **Enhanced Error Decorator**
   - Optional context logging (enabled by default)
   - Works with both XomifyError and generic exceptions
   - Zero code changes needed in existing handlers

## Files Modified

### [lambdas/common/errors.py](lambdas/common/errors.py)

**Added:**

- `mask_sensitive_data()` - Recursively masks sensitive fields
- `log_error_context()` - Logs request context with masking
- Enhanced `@handle_errors()` decorator with `log_context` parameter

**Sensitive Fields List:**

```python
SENSITIVE_FIELDS = {
    'refreshToken', 'refresh_token',
    'accessToken', 'access_token',
    'password', 'passwd',
    'secret', 'apiKey', 'api_key',
    'authorization', 'Authorization',
    'sessionToken', 'privateKey', 'clientSecret'
}
```

## Documentation Added

1. **[lambdas/common/ERROR_HANDLING.md](lambdas/common/ERROR_HANDLING.md)**
   - Complete guide to error handling
   - Usage examples
   - Best practices
   - CloudWatch integration

2. **[lambdas/common/SENSITIVE_FIELDS.md](lambdas/common/SENSITIVE_FIELDS.md)**
   - List of masked fields
   - Pattern-based masking rules
   - Security notes
   - How to add new sensitive fields

3. **[tests/test_error_handling.py](tests/test_error_handling.py)**
   - Tests for masking functionality
   - Tests for decorator behavior
   - Examples of proper usage

## Usage Examples

### Before (No Context Logging)

```python
@handle_errors("my_handler")
def handler(event, context):
    # Error occurs...
    raise ValidationError("Invalid email")

# Logs only:
# ERROR: 💥 ValidationError in my_handler: Invalid email
```

### After (With Context Logging)

```python
@handle_errors("my_handler")  # log_context=True by default
def handler(event, context):
    # Error occurs...
    raise ValidationError("Invalid email")

# Logs:
# ERROR: 💥 ValidationError in my_handler: Invalid email
# ERROR: 📋 Error Context for my_handler.handler:
# ERROR:    Method: POST
# ERROR:    Path: /user/user-table
# ERROR:    Query Params: {"userId": "123"}
# ERROR:    Headers: {"Content-Type": "application/json", "Authorization": "***MASKED***"}
# ERROR:    Body: {"email": "test@example.com", "refreshToken": "***MASKED***"}
# ERROR:    Request ID: abc-123-def
```

### Disable Context Logging (Performance)

```python
@handle_errors("my_handler", log_context=False)
def handler(event, context):
    # High-frequency endpoint, skip context logging
    pass
```

## Example Error Log Output

When an error occurs in production, you'll see:

```
2024-01-28 10:30:45 ERROR: 💥 Unexpected error in friends_accept: An error occurred (ValidationException)...
2024-01-28 10:30:45 ERROR: Traceback (most recent call last):
  File "/var/task/lambdas/common/friendships_dynamo.py", line 117, in accept_friend_request
    ...
2024-01-28 10:30:45 ERROR: 📋 Error Context for friends_accept.handler:
2024-01-28 10:30:45 ERROR:    Method: POST
2024-01-28 10:30:45 ERROR:    Path: /friends/accept
2024-01-28 10:30:45 ERROR:    Query Params: {}
2024-01-28 10:30:45 ERROR:    Headers: {'Content-Type': 'application/json', 'Host': 'api.xomify.xomware.com', 'Authorization': '***MASKED***'}
2024-01-28 10:30:45 ERROR:    Body: {'email': 'user@example.com', 'requestEmail': 'friend@example.com'}
2024-01-28 10:30:45 ERROR:    Request ID: a1b2c3d4-e5f6-7890-abcd-ef1234567890
2024-01-28 10:30:45 ERROR:    Function: xomify-friends-accept
```

## Testing

Run the new tests:

```bash
# Test masking functionality
pytest tests/test_error_handling.py -v

# Test specific masking scenarios
pytest tests/test_error_handling.py::test_mask_sensitive_fields -v
pytest tests/test_error_handling.py::test_mask_authorization_header -v
```

## Migration

### Existing Handlers - No Changes Needed! ✅

All existing handlers using `@handle_errors()` will automatically get:

- ✅ Context logging on errors
- ✅ Sensitive data masking
- ✅ Enhanced error messages

### Optional Optimization

For high-frequency endpoints, you can disable context logging:

```python
# Before
@handle_errors("high_frequency_handler")

# After (optional optimization)
@handle_errors("high_frequency_handler", log_context=False)
```

## Security Benefits

1. **Prevents Token Leakage** - Refresh tokens, access tokens never appear in logs
2. **Password Protection** - Passwords automatically masked if accidentally logged
3. **API Key Safety** - API keys and secrets masked automatically
4. **Header Protection** - Authorization headers masked in all logs
5. **Long String Safety** - Potential encoded tokens truncated

## CloudWatch Insights Queries

Find errors with context:

```sql
fields @timestamp, @message
| filter @message like /📋 Error Context/
| sort @timestamp desc
| limit 20
```

Find masked tokens (should return nothing):

```sql
fields @timestamp, @message
| filter @message like /refreshToken/ and @message not like /***MASKED***/
| sort @timestamp desc
```

## Performance Impact

- **Minimal** - Only runs when errors occur
- **No impact on success path** - Happy path unchanged
- **Optional** - Can disable with `log_context=False`
- **Memory efficient** - Masking creates shallow copies

## Future Enhancements

Potential additions:

- [ ] Mask credit card numbers
- [ ] Mask email addresses (optional)
- [ ] Configurable masking rules per handler
- [ ] Structured logging (JSON format)
- [ ] Custom masking patterns via config
