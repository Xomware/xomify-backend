# Lambda Tests

This directory contains unit tests for all Lambda functions.

## Running Tests

### Run all tests
```bash
pytest tests/ -v
```

### Run tests for a specific lambda
```bash
pytest tests/test_user_get.py -v
```

### Run tests with coverage
```bash
pytest tests/ -v --cov=lambdas --cov-report=html
```

### Run tests for changed lambdas only
```bash
# Example: test only friends_list and user_get
pytest tests/test_friends_list.py tests/test_user_get.py -v
```

## Test Structure

Each lambda has a corresponding test file:
- `test_<lambda_name>.py` - Tests for that specific lambda

### Shared Fixtures

`conftest.py` contains shared pytest fixtures:
- `mock_context` - Mock AWS Lambda context
- `api_gateway_event` - Base API Gateway event structure
- `sample_user` - Sample user data
- `sample_friendship` - Sample friendship data
- `sample_top_items` - Sample Spotify top items

## Writing New Tests

When creating a new lambda, add a corresponding test file:

```python
"""
Tests for <lambda_name> lambda
"""

import pytest
from unittest.mock import patch
from lambdas.<lambda_name>.handler import handler


@patch('lambdas.<lambda_name>.handler.<external_function>')
def test_<lambda_name>_success(mock_function, mock_context, api_gateway_event):
    """Test successful execution"""
    # Setup
    mock_function.return_value = {"success": True}
    event = {
        **api_gateway_event,
        "path": "/<your-path>",
        "queryStringParameters": {"param": "value"}
    }

    # Execute
    response = handler(event, mock_context)

    # Assert
    assert response['statusCode'] == 200
```

## CI/CD Integration

Tests run automatically in GitHub Actions:
- Tests run before deployment
- Only changed lambdas are tested
- Deployment is blocked if tests fail
- Coverage reports are generated

## Test Requirements

Install test dependencies:
```bash
pip install pytest pytest-cov moto boto3
```

## Mock Data

All tests use dummy/mock data - no real AWS resources or Spotify API calls are made during testing.
