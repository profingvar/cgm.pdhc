from flask import request, jsonify, g
from . import api_bp
from .auth import require_api_key
from ..services import (
    TaskIntakeService,
    AcknowledgementService,
    CarePlanDetailsService,
    GuidedResponseService,
    ObservationSubmissionService,
    ReportSubmissionService,
    ReceiptService,
)
from ..errors import APIError


@api_bp.route('/provider-tasks/<receipt_token>', methods=['GET'])
@require_api_key(scope='read')
def get_task(receipt_token):
    task = TaskIntakeService.get_by_receipt_token(receipt_token, g.provider.guid)
    return jsonify(task.to_dict())


@api_bp.route('/provider-tasks/my', methods=['GET'])
@require_api_key(scope='read')
def list_my_tasks():
    status = request.args.get('status')
    limit = request.args.get('limit', 50, type=int)
    tasks = TaskIntakeService.list_tasks(g.provider.guid, status=status, limit=limit)
    return jsonify([t.to_dict() for t in tasks])


@api_bp.route('/provider-tasks/<receipt_token>/accept', methods=['POST'])
@require_api_key(scope='write')
def accept_task(receipt_token):
    data = request.get_json(silent=True) or {}
    task = AcknowledgementService.acknowledge(
        receipt_token, g.provider.guid, notes=data.get('notes')
    )
    return jsonify(task.to_dict())


@api_bp.route('/provider-tasks/<receipt_token>/observe', methods=['POST'])
@require_api_key(scope='write')
def submit_observations(receipt_token):
    """Submit a continuous observation batch. Can be called repeatedly
    while the task is in 'acknowledged' or 'monitoring' status.
    """
    data = request.get_json()
    if not data or 'observations' not in data:
        raise APIError('observations array is required', code='VALIDATION_ERROR', status_code=400)

    observations = data['observations']

    # Validate against careplan if available
    try:
        careplan = CarePlanDetailsService.get_details(receipt_token, g.provider.guid)
        transactions = []
        for activity in careplan.get('activities', []):
            transactions.extend(activity.get('transactions', []))
        if transactions:
            GuidedResponseService.validate_observations(observations, transactions)
    except APIError as e:
        if e.code == 'CAREPLAN_NOT_FOUND':
            pass  # allow submission without careplan validation
        else:
            raise

    task, log_entry = ObservationSubmissionService.submit_batch(
        receipt_token=receipt_token,
        provider_guid=g.provider.guid,
        observations=observations,
    )

    return jsonify({
        'batch_number': log_entry.batch_number,
        'observation_count': log_entry.observation_count,
        'gateway_status': log_entry.gateway_status,
        'task_status': task.status,
        'total_observations_submitted': task.total_observations_submitted,
    }), 202


@api_bp.route('/provider-tasks/<receipt_token>/observe/complete', methods=['POST'])
@require_api_key(scope='write')
def complete_monitoring(receipt_token):
    """Mark monitoring as complete. Stops the auto-stream and sends final status to gateway."""
    data = request.get_json(silent=True) or {}
    task = ObservationSubmissionService.complete_monitoring(
        receipt_token, g.provider.guid, notes=data.get('notes')
    )
    return jsonify(task.to_dict())


@api_bp.route('/provider-tasks/<receipt_token>/observe/status', methods=['GET'])
@require_api_key(scope='read')
def get_stream_status(receipt_token):
    """Check whether a glucose auto-stream is running for this task."""
    from ..services.observation_streamer import get_stream_status
    task = TaskIntakeService.get_by_receipt_token(receipt_token, g.provider.guid)
    status = get_stream_status(receipt_token)
    status['task_status'] = task.status
    status['total_observations_submitted'] = task.total_observations_submitted
    status['last_observation_at'] = task.last_observation_at.isoformat() if task.last_observation_at else None
    return jsonify(status)


@api_bp.route('/provider-tasks/<receipt_token>/observe/log', methods=['GET'])
@require_api_key(scope='read')
def get_observation_log(receipt_token):
    """Get the observation batch log for a task."""
    limit = request.args.get('limit', 50, type=int)
    entries = ObservationSubmissionService.get_observation_log(
        receipt_token, g.provider.guid, limit=limit
    )
    return jsonify([e.to_dict() for e in entries])


@api_bp.route('/provider-tasks/<receipt_token>/report', methods=['POST'])
@require_api_key(scope='write')
def submit_report(receipt_token):
    data = request.get_json()
    if not data or 'provider_payload' not in data:
        raise APIError('provider_payload is required', code='VALIDATION_ERROR', status_code=400)

    provider_payload = data['provider_payload']

    # If guided mode with observations, validate against careplan
    if 'observations' in provider_payload:
        try:
            careplan = CarePlanDetailsService.get_details(receipt_token, g.provider.guid)
            transactions = []
            for activity in careplan.get('activities', []):
                transactions.extend(activity.get('transactions', []))
            GuidedResponseService.validate_observations(provider_payload['observations'], transactions)
        except APIError as e:
            if e.code == 'CAREPLAN_NOT_FOUND':
                pass
            else:
                raise

    task, receipt = ReportSubmissionService.submit(
        receipt_token=receipt_token,
        provider_guid=g.provider.guid,
        provider_payload=provider_payload,
        notes=data.get('notes'),
        receipt_message=data.get('receipt_message'),
    )
    return jsonify({
        'task': task.to_dict(),
        'receipt': receipt.to_dict(),
    })


@api_bp.route('/provider-tasks/<receipt_token>/careplan-details', methods=['GET'])
@require_api_key(scope='read')
def get_careplan_details(receipt_token):
    details = CarePlanDetailsService.get_details(receipt_token, g.provider.guid)
    return jsonify(details)


@api_bp.route('/provider-receipts', methods=['GET'])
@require_api_key(scope='read')
def list_receipts():
    receipt_token = request.args.get('receipt_token')
    limit = request.args.get('limit', 50, type=int)
    receipts = ReceiptService.get_receipts(
        g.provider.guid, receipt_token=receipt_token, limit=limit
    )
    return jsonify([r.to_dict() for r in receipts])
