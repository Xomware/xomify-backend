# Sensitive Fields Reference

## Automatically Masked Fields

The error handling system automatically masks these exact field names:

### Tokens
- `refreshToken` / `refresh_token`
- `accessToken` / `access_token`
- `sessionToken` / `session_token`

### Authentication
- `password` / `passwd`
- `secret`
- `apiKey` / `api_key`
- `clientSecret` / `client_secret`
- `privateKey` / `private_key`
- `authorization` / `Authorization`

### Headers
- `X-API-Key` / `x-api-key`

## Pattern-Based Masking

Any field name containing these substrings (case-insensitive) will also be masked:

- `token` → `userToken`, `resetToken`, `authToken`, etc.
- `password` → `oldPassword`, `newPassword`, etc.
- `secret` → `clientSecret`, `apiSecret`, etc.
- `key` → `apiKey`, `privateKey`, `publicKey`, etc.
- `auth` → `authHeader`, `authCode`, etc.

## Long String Truncation

Strings longer than 100 characters are truncated to prevent logging of encoded tokens:

```python
# Original
"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"

# Logged as
"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOi...[truncated]...dQssw5c"
```

## Examples

### API Gateway Event - Before Masking

```json
{
  "httpMethod": "POST",
  "path": "/user/user-table",
  "headers": {
    "Content-Type": "application/json",
    "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  },
  "body": {
    "email": "user@example.com",
    "userId": "spotify123",
    "refreshToken": "AQDFj8234kjsdf923jkSDf...",
    "displayName": "John Doe"
  }
}
```

### After Masking (What Gets Logged)

```json
{
  "httpMethod": "POST",
  "path": "/user/user-table",
  "headers": {
    "Content-Type": "application/json",
    "Authorization": "***MASKED***"
  },
  "body": {
    "email": "user@example.com",
    "userId": "spotify123",
    "refreshToken": "***MASKED***",
    "displayName": "John Doe"
  }
}
```

## Adding New Sensitive Fields

To add more fields to the sensitive list, edit `lambdas/common/errors.py`:

```python
SENSITIVE_FIELDS = {
    'refreshToken', 'refresh_token',
    # Add your new fields here
    'customSecretField',
    'anotherSensitiveField'
}
```

## Testing Masking

Always test that new sensitive fields are properly masked:

```python
from lambdas.common.errors import mask_sensitive_data

def test_new_sensitive_field():
    data = {"customSecretField": "sensitive_value"}
    masked = mask_sensitive_data(data)
    assert masked["customSecretField"] == "***MASKED***"
```

## Security Notes

- Masking happens **only in logs**, not in actual function execution
- The original values are still used for business logic
- Masking is defensive - even if a field is accidentally logged, it won't expose secrets
- CloudWatch logs are the primary target for masking
- Error responses to users do NOT include request bodies or headers

## Common Mistakes

### ❌ Don't Do This

```python
# Logging sensitive data directly
log.info(f"User token: {user.refreshToken}")  # BAD!
```

### ✅ Do This Instead

```python
# Let the error handler mask it automatically
log.info(f"Processing user: {user.email}")  # GOOD

# Or explicitly mask if needed
from lambdas.common.errors import mask_sensitive_data
safe_user = mask_sensitive_data(user)
log.info(f"User data: {safe_user}")  # GOOD
```
