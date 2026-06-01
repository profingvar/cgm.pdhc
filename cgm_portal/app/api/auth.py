from functools import wraps
from flask import request, g
from ..services import AccessSessionService


def require_api_key(scope='read'):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            raw_key = request.headers.get('X-API-Key')
            provider, api_key = AccessSessionService.authenticate(raw_key)
            AccessSessionService.require_scope(api_key, scope)
            g.provider = provider
            g.api_key = api_key
            return f(*args, **kwargs)
        return decorated
    return decorator
