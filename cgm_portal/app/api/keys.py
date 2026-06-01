import secrets
from datetime import datetime, timezone
from flask import request, jsonify, g
from . import api_bp
from .auth import require_api_key
from ..models import ApiKey
from ..extensions import db
from ..errors import APIError


@api_bp.route('/api-keys', methods=['POST'])
@require_api_key(scope='write')
def create_api_key():
    data = request.get_json()
    if not data:
        raise APIError('Request body required', code='VALIDATION_ERROR', status_code=400)

    scopes = data.get('scopes', 'read')
    label = data.get('label')
    raw_key = secrets.token_urlsafe(32)

    expires_at = None
    if data.get('expires_in_days'):
        from datetime import timedelta
        expires_at = datetime.now(timezone.utc) + timedelta(days=data['expires_in_days'])

    key = ApiKey.create(
        provider_guid=g.provider.guid,
        raw_key=raw_key,
        scopes=scopes,
        label=label,
        expires_at=expires_at,
    )
    db.session.add(key)
    db.session.commit()

    return jsonify({
        'guid': key.guid,
        'key': raw_key,
        'scopes': key.scopes,
        'label': key.label,
        'expires_at': key.expires_at.isoformat() if key.expires_at else None,
        'message': 'Store this key securely. It will not be shown again.',
    }), 201


@api_bp.route('/api-keys/<guid>/revoke', methods=['POST'])
@require_api_key(scope='write')
def revoke_api_key(guid):
    key = ApiKey.query.filter_by(guid=guid, provider_guid=g.provider.guid).first()
    if not key:
        raise APIError('API key not found', code='NOT_FOUND', status_code=404)
    if key.revoked:
        return jsonify({'message': 'Key already revoked', 'guid': guid})

    key.revoked = True
    db.session.commit()
    return jsonify({'message': 'Key revoked', 'guid': guid})


@api_bp.route('/api-keys/<guid>/rotate', methods=['POST'])
@require_api_key(scope='write')
def rotate_api_key(guid):
    old_key = ApiKey.query.filter_by(guid=guid, provider_guid=g.provider.guid).first()
    if not old_key:
        raise APIError('API key not found', code='NOT_FOUND', status_code=404)

    new_raw_key = secrets.token_urlsafe(32)
    new_key = ApiKey.create(
        provider_guid=g.provider.guid,
        raw_key=new_raw_key,
        scopes=old_key.scopes,
        label=f'rotated-{old_key.label or old_key.guid[:8]}',
        expires_at=old_key.expires_at,
    )
    db.session.add(new_key)

    old_key.revoked = True
    db.session.commit()

    return jsonify({
        'old_key_guid': guid,
        'new_key_guid': new_key.guid,
        'key': new_raw_key,
        'scopes': new_key.scopes,
        'message': 'Old key revoked. Store new key securely.',
    }), 201
