import os
import boto3
from lambdas.common.constants import PRODUCT
from lambdas.common.logger import get_logger

log = get_logger(__file__)

__SPOTIFY_ROOT = f'/{PRODUCT}/spotify/'
__API_ROOT = f'/{PRODUCT}/api/'

# Lazy-initialized SSM parameters (#122)
_ssm_cache: dict[str, str] = {}


def _get_ssm_param(name: str) -> str:
    """Fetch an SSM parameter with lazy initialization and caching."""
    if name not in _ssm_cache:
        try:
            ssm = boto3.client("ssm")
            _ssm_cache[name] = ssm.get_parameter(
                Name=name, WithDecryption=True
            )['Parameter']['Value']
        except Exception as err:
            log.error(f"Failed to fetch SSM parameter '{name}': {err}")
            raise RuntimeError(f"SSM parameter '{name}' could not be loaded: {err}") from err
    return _ssm_cache[name]


def _apns_param_path(key: str) -> str:
    """Resolve APNs SSM path, honoring env-var override from terraform."""
    env_name = f'APNS_{key}_PARAM'
    override = os.environ.get(env_name)
    if override:
        return override
    return f'/{PRODUCT}/apns/{key}'


def __getattr__(name: str) -> str:
    """Module-level __getattr__ for lazy SSM parameter access."""
    param_map = {
        'SPOTIFY_CLIENT_ID': f'{__SPOTIFY_ROOT}CLIENT_ID',
        'SPOTIFY_CLIENT_SECRET': f'{__SPOTIFY_ROOT}CLIENT_SECRET',
        'API_SECRET_KEY': f'{__API_ROOT}API_SECRET_KEY',
        'APNS_AUTH_KEY': _apns_param_path('AUTH_KEY'),
        'APNS_KEY_ID': _apns_param_path('KEY_ID'),
        'APNS_TEAM_ID': _apns_param_path('TEAM_ID'),
        'APNS_BUNDLE_ID': _apns_param_path('BUNDLE_ID'),
    }
    if name in param_map:
        return _get_ssm_param(param_map[name])
    raise AttributeError(f"module 'ssm_helpers' has no attribute {name!r}")
