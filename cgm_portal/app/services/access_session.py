from ..models import Provider, ApiKey
from ..errors import APIError


class AccessSessionService:

    @staticmethod
    def authenticate(raw_key):
        if not raw_key:
            raise APIError('Missing API key', code='AUTH_MISSING', status_code=401)

        keys = ApiKey.query.all()
        for api_key in keys:
            if api_key.verify(raw_key):
                if not api_key.is_valid():
                    raise APIError('API key expired or revoked', code='AUTH_INVALID', status_code=401)
                provider = Provider.query.filter_by(guid=api_key.provider_guid).first()
                if not provider or not provider.is_active:
                    raise APIError('Provider inactive', code='AUTH_PROVIDER_INACTIVE', status_code=403)
                return provider, api_key
        raise APIError('Invalid API key', code='AUTH_INVALID', status_code=401)

    @staticmethod
    def require_scope(api_key, scope):
        if not api_key.has_scope(scope):
            raise APIError(
                f'Insufficient scope: requires {scope}',
                code='AUTH_SCOPE_MISMATCH',
                status_code=403,
            )
