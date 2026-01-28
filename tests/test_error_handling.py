"""
Tests for error handling and sensitive data masking
"""

import pytest
import json
from lambdas.common.errors import mask_sensitive_data, handle_errors, XomifyError


def test_mask_sensitive_fields():
    """Test that sensitive fields are masked"""
    data = {
        "email": "test@example.com",
        "refreshToken": "secret_token_12345",
        "userId": "user123",
        "password": "mypassword",
        "normalField": "visible"
    }

    masked = mask_sensitive_data(data)

    assert masked["email"] == "test@example.com"
    assert masked["refreshToken"] == "***MASKED***"
    assert masked["password"] == "***MASKED***"
    assert masked["normalField"] == "visible"
    assert masked["userId"] == "user123"


def test_mask_nested_data():
    """Test masking in nested structures"""
    data = {
        "user": {
            "email": "test@example.com",
            "accessToken": "secret_access_token"
        },
        "credentials": {
            "apiKey": "super_secret_key",
            "publicId": "public123"
        }
    }

    masked = mask_sensitive_data(data)

    assert masked["user"]["email"] == "test@example.com"
    assert masked["user"]["accessToken"] == "***MASKED***"
    assert masked["credentials"]["apiKey"] == "***MASKED***"
    assert masked["credentials"]["publicId"] == "public123"


def test_mask_list_of_objects():
    """Test masking in lists"""
    data = [
        {"name": "User1", "refreshToken": "token1"},
        {"name": "User2", "secret": "secret2"}
    ]

    masked = mask_sensitive_data(data)

    assert masked[0]["name"] == "User1"
    assert masked[0]["refreshToken"] == "***MASKED***"
    assert masked[1]["name"] == "User2"
    assert masked[1]["secret"] == "***MASKED***"


def test_mask_authorization_header():
    """Test that authorization headers are masked"""
    data = {
        "headers": {
            "Content-Type": "application/json",
            "Authorization": "Bearer secret_jwt_token_here",
            "X-API-Key": "my_api_key"
        }
    }

    masked = mask_sensitive_data(data)

    assert masked["headers"]["Content-Type"] == "application/json"
    assert masked["headers"]["Authorization"] == "***MASKED***"
    assert masked["headers"]["X-API-Key"] == "***MASKED***"


def test_truncate_long_strings():
    """Test that very long strings are truncated"""
    long_string = "a" * 200
    data = {"longField": long_string}

    masked = mask_sensitive_data(data)

    assert len(masked["longField"]) < len(long_string)
    assert "truncated" in masked["longField"]


def test_handle_errors_decorator_with_xomify_error(mock_context, api_gateway_event):
    """Test decorator catches XomifyError and returns proper response"""

    @handle_errors("test_handler", log_context=False)
    def failing_handler(event, context):
        raise XomifyError("Test error", handler="test", function="test_func", status=400)

    response = failing_handler(api_gateway_event, mock_context)

    assert response['statusCode'] == 400
    body = json.loads(response['body'])
    assert body['error']['message'] == "Test error"


def test_handle_errors_decorator_with_generic_exception(mock_context, api_gateway_event):
    """Test decorator catches generic exceptions"""

    @handle_errors("test_handler", log_context=False)
    def failing_handler(event, context):
        raise ValueError("Unexpected error")

    response = failing_handler(api_gateway_event, mock_context)

    assert response['statusCode'] == 500
    body = json.loads(response['body'])
    assert "Unexpected error" in body['error']['message']


def test_custom_mask_value():
    """Test using custom mask value"""
    data = {"password": "secret123"}
    masked = mask_sensitive_data(data, mask_value="[REDACTED]")

    assert masked["password"] == "[REDACTED]"


def test_case_insensitive_token_masking():
    """Test that fields containing 'token' are masked regardless of case"""
    data = {
        "accessToken": "secret1",
        "refresh_token": "secret2",
        "userToken": "secret3",
        "tokenExpiry": 3600  # This should also be masked as it contains 'token'
    }

    masked = mask_sensitive_data(data)

    assert masked["accessToken"] == "***MASKED***"
    assert masked["refresh_token"] == "***MASKED***"
    assert masked["userToken"] == "***MASKED***"
    # Note: tokenExpiry gets masked because key contains 'token'
