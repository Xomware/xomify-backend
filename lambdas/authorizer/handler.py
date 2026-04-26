from typing import Any, Optional

import jwt
from lambdas.common.constants import PRODUCT
from lambdas.common.ssm_helpers import API_SECRET_KEY
from lambdas.common.errors import LambdaAuthorizerError
from lambdas.common.logger import get_logger

log = get_logger(__file__)

HANDLER = 'authorizer'

# Custom-authorizer context values must be string/number/bool only.
TOKEN_TYPE_USER = "user"
TOKEN_TYPE_LEGACY = "legacy"


def generate_policy(effect: str, resource: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Return a valid AWS API Gateway custom-authorizer policy response.

    When `context` is provided, it is included under the `"context"` key of
    the response. API Gateway only accepts string/number/bool values in the
    context dict — callers are responsible for ensuring values conform.
    """
    auth_response: dict[str, Any] = {
        'principalId': PRODUCT,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Action': 'execute-api:*',
                    'Effect': effect,
                    'Resource': resource
                }
            ]
        }
    }
    if context is not None:
        auth_response['context'] = context
    return auth_response

def decode_auth_token(auth_token: str) -> Optional[dict[str, Any]]:
    """Decodes the auth token. Returns the decoded payload, or None on failure."""
    try:
        # remove "Bearer " from the token string.
        auth_token = auth_token.replace('Bearer ', '')
        # decode using system environ $SECRET_KEY, will crash if not set.
        return jwt.decode(auth_token, API_SECRET_KEY, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        log.warning('Signature expired. Please log in again.')
        return None
    except jwt.InvalidTokenError:
        log.warning('Invalid token. Please log in again.')
        return None


def _build_allow_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Inspect the decoded JWT payload and produce the authorizer context.

    Per-user JWT (both `email` and `userId` are non-empty strings):
        returns { email, userId, tokenType: "user" } and logs auth_path=context.
    Legacy static token (either claim missing/empty/non-string):
        returns { tokenType: "legacy" } and logs auth_path=fallback so we can
        monitor migration progress (Q5 of the parent epic).
    """
    email = payload.get('email')
    user_id = payload.get('userId')

    if isinstance(email, str) and email and isinstance(user_id, str) and user_id:
        log.info(f"auth_path=context email={email} tokenType={TOKEN_TYPE_USER}")
        return {
            'email': email,
            'userId': user_id,
            'tokenType': TOKEN_TYPE_USER,
        }

    log.info(f"auth_path=fallback tokenType={TOKEN_TYPE_LEGACY}")
    return {'tokenType': TOKEN_TYPE_LEGACY}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method_arn = event.get('methodArn', '')
    try:
        auth_token = event.get('authorizationToken', '')

        if auth_token and method_arn:
            user_details = decode_auth_token(auth_token)
            if user_details is not None:
                arn_parts = method_arn.split(':')
                api_gateway_arn_tmp = arn_parts[5].split('/')
                # Construct: arn:aws:execute-api:region:account:apiId/stage/*
                resource_arn = f"{arn_parts[0]}:{arn_parts[1]}:{arn_parts[2]}:{arn_parts[3]}:{arn_parts[4]}:{api_gateway_arn_tmp[0]}/{api_gateway_arn_tmp[1]}/*"

                allow_context = _build_allow_context(user_details)
                return generate_policy('Allow', resource_arn, context=allow_context)

        log.warning("Authorizer: Deny.")
        return generate_policy('Deny', method_arn)
    except Exception as err:
        message = str(err)
        log.error(f"Error in Lambda Authorizer: {message}")
        LambdaAuthorizerError(message, HANDLER, 'handler')
        return generate_policy('Deny', method_arn)
