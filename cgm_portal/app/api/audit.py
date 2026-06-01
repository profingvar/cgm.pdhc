from flask import request, jsonify, g
from . import api_bp
from .auth import require_api_key
from ..models import TaskAuditLog
from ..errors import APIError


@api_bp.route('/audit-log', methods=['GET'])
@require_api_key(scope='read')
def list_audit_log():
    receipt_token = request.args.get('receipt_token')
    limit = request.args.get('limit', 50, type=int)

    query = TaskAuditLog.query.filter_by(provider_guid=g.provider.guid)
    if receipt_token:
        query = query.filter_by(receipt_token=receipt_token)
    entries = query.order_by(TaskAuditLog.created_at.desc()).limit(limit).all()
    return jsonify([e.to_dict() for e in entries])


@api_bp.route('/audit-log/<guid>', methods=['GET'])
@require_api_key(scope='read')
def get_audit_entry(guid):
    entry = TaskAuditLog.query.filter_by(guid=guid, provider_guid=g.provider.guid).first()
    if not entry:
        raise APIError('Audit entry not found', code='NOT_FOUND', status_code=404)
    return jsonify(entry.to_dict())
