"""Key revocation, expiry and rotation (#945).

Ported from provider.pdhc's tests/test_security.py, which covers the SAME
code: cgm's app/api/auth.py, app/api/keys.py and app/models/api_key.py are
code-identical to provider's (measured 2026-11-06 on the parse tree), while
cgm had no test touching revocation or expiry at all.

Every assertion goes through the real HTTP entry point, not through
ApiKey.is_valid() in isolation — the question is whether the control is
REACHED on a request, which a unit test of the predicate cannot answer
(feedback_test_the_dish_not_the_ingredient).

The two CONTROL tests at the bottom are not in provider's file and are the
reason the rejections above them count as evidence: without them, every
"rejected" assertion would also pass if the endpoint rejected all keys, or if
any key carrying an expires_at were refused regardless of the date.
"""
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import ApiKey

PROTECTED = '/api/v1/provider-tasks/my'


def test_key_is_hashed(provider, api_key):
    assert api_key.key_hash != 'test-api-key'
    assert api_key.verify('test-api-key')
    assert not api_key.verify('wrong-key')


def test_revoked_key_rejected(client, provider, api_key, app):
    api_key.revoked = True
    db.session.commit()

    resp = client.get(PROTECTED, headers={'X-API-Key': 'test-api-key'})
    assert resp.status_code == 401


def test_expired_key_rejected(client, provider, app):
    key = ApiKey.create(
        provider_guid=provider.guid,
        raw_key='expired-key',
        scopes='read,write',
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db.session.add(key)
    db.session.commit()

    resp = client.get(PROTECTED, headers={'X-API-Key': 'expired-key'})
    assert resp.status_code == 401


def test_key_rotation_api(client, provider, api_key, auth_headers, app):
    resp = client.post(f'/api/v1/api-keys/{api_key.guid}/rotate', headers=auth_headers)
    assert resp.status_code == 201
    data = resp.get_json()
    assert 'key' in data
    assert data['old_key_guid'] == api_key.guid

    db.session.refresh(api_key)
    assert api_key.revoked is True

    new_headers = {'X-API-Key': data['key'], 'Content-Type': 'application/json'}
    resp = client.get(PROTECTED, headers=new_headers)
    assert resp.status_code == 200

    # provider.pdhc's original stops at `revoked is True` above. That is a
    # field value, not a decision: under a mutation that makes is_valid()
    # always return True, the assertion still holds while the rotated-away key
    # is happily accepted. Rotation's whole security value is that the OLD
    # secret stops working, so assert that instead of the flag.
    resp = client.get(PROTECTED, headers={'X-API-Key': 'test-api-key'})
    assert resp.status_code == 401


def test_key_revocation_api(client, provider, api_key, auth_headers, app):
    # A second key first, so the revoke call itself can still authenticate.
    resp = client.post('/api/v1/api-keys', headers=auth_headers,
                       json={'scopes': 'read,write', 'label': 'backup'})
    assert resp.status_code == 201
    backup_key = resp.get_json()['key']

    resp = client.post(f'/api/v1/api-keys/{api_key.guid}/revoke',
                       headers={'X-API-Key': backup_key, 'Content-Type': 'application/json'})
    assert resp.status_code == 200

    resp = client.get(PROTECTED, headers={'X-API-Key': 'test-api-key'})
    assert resp.status_code == 401


def test_create_key_with_expiry(client, provider, api_key, auth_headers, app):
    resp = client.post('/api/v1/api-keys', headers=auth_headers,
                       json={'scopes': 'read', 'label': 'temp', 'expires_in_days': 30})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data['expires_at'] is not None
    assert data['scopes'] == 'read'


# --------------------------------------------------------------------------
# CONTROLS — not in provider's file. Without these, the rejections above
# would also hold if the endpoint refused every key.
# --------------------------------------------------------------------------

def test_CONTROL_unrevoked_unexpired_key_is_accepted(client, provider, api_key, app):
    """The rejections above are only evidence if the same call succeeds."""
    resp = client.get(PROTECTED, headers={'X-API-Key': 'test-api-key'})
    assert resp.status_code == 200


def test_CONTROL_future_expiry_is_accepted(client, provider, app):
    """A key WITH an expires_at, in the future, must still be accepted.

    Without this, test_expired_key_rejected would pass unchanged against an
    implementation that refused any key carrying an expiry date at all.
    """
    key = ApiKey.create(
        provider_guid=provider.guid,
        raw_key='future-key',
        scopes='read,write',
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.session.add(key)
    db.session.commit()

    resp = client.get(PROTECTED, headers={'X-API-Key': 'future-key'})
    assert resp.status_code == 200
