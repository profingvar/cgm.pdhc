"""Gateway receipt ingestion — receives observation receipts from gateway.pdhc."""
import logging
from datetime import datetime, timezone
from flask import request, jsonify, current_app
from . import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/receipts/ingest', methods=['POST'])
def ingest_receipt():
    """Receive a receipt pushed from gateway.pdhc.

    Accepted credentials (try in order):
      1. `GATEWAY_SERVICE_KEY` — legacy shared key, kept for compatibility.
      2. `PUSH_SECRET` — the same secret gateway sends on inbound pushes,
         which is also what's now stored on the PAT record in request.pdhc
         as push_auth_key. Matching against PUSH_SECRET lets gateway reuse
         one secret for both directions (push IN, receipt OUT) per PAT.

    The 503 'not_configured' only fires if BOTH are empty — that's a real
    misconfiguration, not a routine state.
    """
    gateway_key = current_app.config.get('GATEWAY_SERVICE_KEY') or ''
    push_secret = current_app.config.get('PUSH_SECRET') or ''
    accepted_keys = [k for k in (gateway_key, push_secret) if k]
    if not accepted_keys:
        logger.error('Neither GATEWAY_SERVICE_KEY nor PUSH_SECRET configured — '
                     'cannot accept gateway receipts')
        return jsonify({'code': 'not_configured', 'message': 'Gateway receipt ingestion not configured'}), 503

    service_key = request.headers.get('X-Service-Key')
    if not service_key or service_key not in accepted_keys:
        logger.warning('Receipt ingest rejected: invalid X-Service-Key from %s', request.remote_addr)
        return jsonify({'code': 'unauthenticated', 'message': 'Invalid service key'}), 401

    data = request.get_json()
    if not data:
        return jsonify({'code': 'bad_request', 'message': 'JSON body required'}), 400

    receipt_guid = data.get('receipt_guid')
    sr_guid = data.get('service_request_guid')
    if not receipt_guid or not sr_guid:
        return jsonify({'code': 'bad_request', 'message': 'receipt_guid and service_request_guid required'}), 400

    try:
        result = _store_receipt(data)
    except Exception as e:
        logger.error('Failed to store gateway receipt: %s', str(e))
        return jsonify({'code': 'internal_error', 'message': 'Failed to store receipt'}), 500

    return jsonify({
        'status': 'accepted',
        'receipt_guid': receipt_guid,
        'action': result,
    }), 202


def _store_receipt(data):
    """Store the gateway receipt, deduplicating by receipt_guid."""
    from ..extensions import db
    from ..models import GatewayReceipt, TaskAuditLog

    receipt_guid = data['receipt_guid']

    existing = GatewayReceipt.query.filter_by(receipt_guid=receipt_guid).first()
    if existing:
        return 'duplicate'

    accepted_at = None
    if data.get('accepted_at'):
        try:
            accepted_at = datetime.fromisoformat(data['accepted_at'].replace('Z', '+00:00'))
        except (ValueError, TypeError):
            accepted_at = datetime.now(timezone.utc)

    receipt = GatewayReceipt(
        receipt_guid=receipt_guid,
        service_request_guid=data['service_request_guid'],
        patient_guid=data.get('patient_guid'),
        provider_org_guid=data.get('provider_org_guid'),
        contract_guid=data.get('contract_guid'),
        observations_stored=data.get('observations_stored', 0),
        accepted_at=accepted_at,
        payload_hash=data.get('payload_hash'),
    )
    db.session.add(receipt)

    provider_guid = current_app.config.get('PROVIDER_GUID')
    db.session.add(TaskAuditLog(
        receipt_token=data['service_request_guid'],
        provider_guid=provider_guid or 'system',
        action='gateway_receipt_ingested',
        payload_snapshot={
            'receipt_guid': receipt_guid,
            'service_request_guid': data['service_request_guid'],
            'observations_stored': data.get('observations_stored', 0),
        },
    ))

    db.session.commit()
    return 'created'
