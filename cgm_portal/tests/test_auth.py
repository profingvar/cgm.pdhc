"""Tests for API key authentication."""


def test_missing_api_key(client):
    resp = client.get('/api/v1/provider-tasks/my')
    assert resp.status_code == 401


def test_invalid_api_key(client):
    resp = client.get('/api/v1/provider-tasks/my',
                       headers={'X-API-Key': 'bad-key'})
    assert resp.status_code == 401


def test_valid_api_key(client, api_key, auth_headers):
    resp = client.get('/api/v1/provider-tasks/my', headers=auth_headers)
    assert resp.status_code == 200


def test_scope_enforcement(client, provider, app):
    """Read-only key cannot call write endpoints."""
    from app.models import ApiKey
    from app.extensions import db
    key = ApiKey.create(
        provider_guid=provider.guid,
        raw_key='read-only-key',
        scopes='read',
        label='readonly',
    )
    db.session.add(key)
    db.session.commit()

    resp = client.post('/api/v1/provider-tasks/test/accept',
                        headers={'X-API-Key': 'read-only-key',
                                 'Content-Type': 'application/json'})
    assert resp.status_code == 403
