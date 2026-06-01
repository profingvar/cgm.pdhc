"""Inbound push receiver — accepts FHIR Bundles pushed from request.pdhc.

Validates X-Push-Secret header for mutual authentication.
Extracts receipt_token and grant_token from bundle meta.tag.
"""
import logging
from flask import request, jsonify, current_app
from . import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/inbound/push', methods=['POST'])
def receive_push():
    """Receive a pushed FHIR Bundle from request.pdhc."""
    expected_secret = current_app.config.get('PUSH_SECRET')
    if not expected_secret:
        return jsonify({'code': 'not_configured', 'message': 'Push reception not configured'}), 503

    push_secret = request.headers.get('X-Push-Secret')
    if not push_secret or push_secret != expected_secret:
        logger.warning('Push rejected: invalid X-Push-Secret from %s', request.remote_addr)
        return jsonify({'code': 'unauthenticated', 'message': 'Invalid push secret'}), 401

    bundle = request.get_json()
    if not bundle:
        return jsonify({'code': 'bad_request', 'message': 'JSON body required'}), 400

    if bundle.get('resourceType') != 'Bundle':
        return jsonify({'code': 'bad_request', 'message': 'Expected FHIR Bundle'}), 400

    # Extract delivery metadata from meta.tag
    receipt_token = None
    grant_token = None
    tag_contract_guid = None
    tag_organisation_guid = None
    tag_expires_at = None
    for tag in bundle.get('meta', {}).get('tag', []):
        code = tag.get('code')
        display = tag.get('display')
        if code == 'receipt_token':
            receipt_token = display
        elif code == 'grant_token':
            grant_token = display
        elif code == 'contract_guid':
            tag_contract_guid = display
        elif code == 'organisation_guid':
            tag_organisation_guid = display
        elif code == 'expires_at':
            tag_expires_at = display

    if not receipt_token:
        return jsonify({'code': 'bad_request', 'message': 'Missing receipt_token in meta.tag'}), 400

    # Extract the ServiceRequest from entry
    fhir_resource = None
    for entry in bundle.get('entry', []):
        resource = entry.get('resource', {})
        if resource.get('resourceType') == 'ServiceRequest':
            fhir_resource = resource
            break

    if not fhir_resource:
        return jsonify({'code': 'bad_request', 'message': 'No ServiceRequest in bundle entries'}), 400

    try:
        result = _process_push(
            fhir_resource, receipt_token, grant_token,
            tag_contract_guid=tag_contract_guid,
            tag_organisation_guid=tag_organisation_guid,
            tag_expires_at=tag_expires_at,
        )
    except Exception as e:
        logger.error('Failed to process push: %s', str(e))
        return jsonify({'code': 'internal_error', 'message': 'Failed to process push'}), 500

    # Acknowledge the push receipt upstream
    try:
        from ..services.upstream_client import UpstreamClient
        provider_token = current_app.config.get('PROVIDER_TOKEN')
        base_url = current_app.config.get('REQUEST_SERVICE_URL')
        if provider_token and base_url:
            client = UpstreamClient(base_url=base_url, provider_token=provider_token)
            client.ack_receipt(receipt_token)
    except Exception as e:
        logger.warning('Failed to ack receipt %s upstream: %s', receipt_token, str(e))

    return jsonify({
        'status': 'accepted',
        'receipt_token': receipt_token,
        'request_guid': result.get('request_guid'),
    }), 202


def _process_push(fhir_resource, receipt_token, grant_token,
                   tag_contract_guid=None, tag_organisation_guid=None,
                   tag_expires_at=None):
    """Store the pushed ServiceRequest as InboundRequest + ProviderTask."""
    from ..extensions import db
    from ..models import InboundRequest, ProviderTask, CarePlanCache, TaskAuditLog
    from ..services.request_mapper import RequestMapper, _extract_careplan, _extract_patient_name, _extract_title
    from datetime import datetime as dt

    provider_guid = current_app.config.get('PROVIDER_GUID')
    sr_guid = fhir_resource.get('id', receipt_token)

    # Extract patient info from FHIR subject
    patient_guid = None
    subject = fhir_resource.get('subject', {})
    ref = subject.get('reference', '')
    if ref.startswith('Patient/'):
        patient_guid = ref.split('/', 1)[1]

    # Extract contract guid
    contract_guid = tag_contract_guid
    if not contract_guid:
        for based_on in fhir_resource.get('basedOn', []):
            ref = based_on.get('reference', '')
            if 'Contract' in ref:
                contract_guid = ref.split('/', 1)[-1] if '/' in ref else ref

    # Parse grant expiry
    grant_expires_at = None
    if tag_expires_at:
        try:
            grant_expires_at = dt.fromisoformat(tag_expires_at.replace('Z', '+00:00'))
        except (ValueError, TypeError):
            pass

    careplan = _extract_careplan(fhir_resource)

    # Extract monitoring parameters from occurrencePeriod
    monitoring_until = None
    occurrence = fhir_resource.get('occurrencePeriod', {})
    if occurrence.get('end'):
        try:
            monitoring_until = dt.fromisoformat(occurrence['end'].replace('Z', '+00:00'))
        except (ValueError, TypeError):
            pass

    # Check for existing
    existing = InboundRequest.query.filter_by(request_guid=sr_guid).first()
    if existing:
        existing.fhir_resource = fhir_resource
        existing.careplan_json = careplan
        existing.grant_token = grant_token
        existing.contract_guid = contract_guid
        existing.organisation_guid = tag_organisation_guid
        existing.grant_expires_at = grant_expires_at
        existing.checksum = InboundRequest.compute_checksum(fhir_resource)
        existing.last_synced_at = db.func.now()
        db.session.commit()
        return {'request_guid': sr_guid, 'action': 'updated'}

    inbound = InboundRequest(
        request_guid=sr_guid,
        provider_guid=provider_guid,
        receipt_token=sr_guid,
        careplan_json=careplan,
        fhir_resource=fhir_resource,
        patient_guid=patient_guid,
        contract_guid=contract_guid,
        organisation_guid=tag_organisation_guid,
        grant_token=grant_token,
        grant_expires_at=grant_expires_at,
        status='new',
        checksum=InboundRequest.compute_checksum(fhir_resource),
    )
    db.session.add(inbound)

    # Create task with monitoring fields
    patient_name = _extract_patient_name(fhir_resource)
    title = _extract_title(fhir_resource, careplan)

    task = ProviderTask(
        receipt_token=sr_guid,
        provider_guid=provider_guid,
        request_guid=sr_guid,
        status='dispatched',
        patient_guid=patient_guid,
        patient_name=patient_name,
        careplan_title=title,
        priority=fhir_resource.get('priority', 'routine'),
        monitoring_until=monitoring_until,
    )
    db.session.add(task)

    # Cache careplan
    if careplan:
        cache = CarePlanCache(receipt_token=sr_guid, careplan_json=careplan)
        db.session.add(cache)

    # Audit
    db.session.add(TaskAuditLog(
        receipt_token=sr_guid,
        provider_guid=provider_guid,
        action='push_received',
        payload_snapshot={
            'request_guid': sr_guid,
            'patient_guid': patient_guid,
            'has_grant': grant_token is not None,
            'monitoring_until': monitoring_until.isoformat() if monitoring_until else None,
        },
    ))

    db.session.commit()
    return {'request_guid': sr_guid, 'action': 'created'}
