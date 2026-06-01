import pytest
from app import create_app
from app.extensions import db as _db
from app.models import Provider, ApiKey
from config import TestConfig


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def provider(app):
    import uuid
    p = Provider(guid=str(uuid.uuid4()), name='Test CGM Provider', is_active=True)
    _db.session.add(p)
    _db.session.commit()
    return p


@pytest.fixture
def api_key(provider):
    key = ApiKey.create(
        provider_guid=provider.guid,
        raw_key='test-api-key',
        scopes='read,write',
        label='test',
    )
    _db.session.add(key)
    _db.session.commit()
    return key


@pytest.fixture
def auth_headers():
    return {'X-API-Key': 'test-api-key', 'Content-Type': 'application/json'}
