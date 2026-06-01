import os
from flask import render_template, request, flash, redirect, url_for, session, current_app, send_file, g
from . import web_bp
from ..models import ProviderTask, SubmissionReceipt, TaskAuditLog, SyncState, InboundRequest, GatewayReceipt, ObservationLog
from ..services import AcknowledgementService
from ..services.observation_submission import ObservationSubmissionService
from ..services.observation_streamer import get_stream_status, list_active_streams
from ..errors import APIError
from pdhc_keyauth import login_required


def _get_provider_guid():
    """Return the provider GUID for this instance (from config)."""
    return current_app.config.get('PROVIDER_GUID')


@web_bp.route('/')
@login_required
def dashboard():
    pguid = _get_provider_guid()
    task_count = ProviderTask.query.filter_by(provider_guid=pguid).count() if pguid else 0
    pending_count = ProviderTask.query.filter_by(provider_guid=pguid, status='dispatched').count() if pguid else 0
    monitoring_count = ProviderTask.query.filter_by(provider_guid=pguid, status='monitoring').count() if pguid else 0
    completed_count = ProviderTask.query.filter_by(provider_guid=pguid, status='completed').count() if pguid else 0
    receipt_count = SubmissionReceipt.query.filter_by(provider_guid=pguid).count() if pguid else 0
    gateway_receipt_count = GatewayReceipt.query.count()
    active_stream_count = len(list_active_streams())
    sync_status = None

    if pguid:
        state = SyncState.query.filter_by(provider_guid=pguid).first()
        sync_status = {
            'provider_name': current_app.config.get('PROVIDER_NAME', '—'),
            'provider_guid': pguid,
            'sync_enabled': current_app.config.get('SYNC_ENABLED', False),
            'last_sync_at': state.last_sync_at if state else None,
            'requests_synced': state.requests_synced if state else 0,
            'last_error': state.last_error if state else None,
            'inbound_count': InboundRequest.query.filter_by(provider_guid=pguid).count(),
        }

    return render_template('dashboard.html',
                           provider_name=current_app.config.get('PROVIDER_NAME', '—'),
                           task_count=task_count,
                           pending_count=pending_count,
                           monitoring_count=monitoring_count,
                           completed_count=completed_count,
                           receipt_count=receipt_count,
                           gateway_receipt_count=gateway_receipt_count,
                           active_stream_count=active_stream_count,
                           sync_status=sync_status)


@web_bp.route('/tasks')
@login_required
def task_list():
    pguid = _get_provider_guid()
    status_filter = request.args.get('status')
    query = ProviderTask.query.filter_by(provider_guid=pguid)
    if status_filter:
        query = query.filter_by(status=status_filter)
    tasks = query.order_by(ProviderTask.created_at.desc()).all()
    return render_template('tasks.html', tasks=tasks, status_filter=status_filter)


@web_bp.route('/tasks/<receipt_token>')
@login_required
def task_detail(receipt_token):
    pguid = _get_provider_guid()
    task = ProviderTask.query.filter_by(
        receipt_token=receipt_token, provider_guid=pguid
    ).first_or_404()
    audit_entries = TaskAuditLog.query.filter_by(
        receipt_token=receipt_token, provider_guid=pguid
    ).order_by(TaskAuditLog.created_at.desc()).limit(50).all()
    inbound = InboundRequest.query.filter_by(
        receipt_token=receipt_token, provider_guid=pguid
    ).first()

    stream_status = get_stream_status(receipt_token)
    observation_logs = ObservationLog.query.filter_by(
        receipt_token=receipt_token
    ).order_by(ObservationLog.submitted_at.desc()).limit(50).all()

    return render_template('task_detail.html', task=task,
                           audit_entries=audit_entries, inbound=inbound,
                           stream_status=stream_status,
                           observation_logs=observation_logs)


@web_bp.route('/tasks/<receipt_token>/accept', methods=['POST'])
@login_required
def accept_task(receipt_token):
    pguid = _get_provider_guid()
    notes = request.form.get('notes', '').strip() or None
    try:
        AcknowledgementService.acknowledge(receipt_token, pguid, notes=notes)
        flash('Task acknowledged — glucose stream started', 'success')
    except APIError as e:
        flash(e.message, 'error')
    return redirect(url_for('web.task_detail', receipt_token=receipt_token))


@web_bp.route('/tasks/<receipt_token>/complete', methods=['POST'])
@login_required
def complete_monitoring(receipt_token):
    pguid = _get_provider_guid()
    try:
        ObservationSubmissionService.complete_monitoring(receipt_token, pguid)
        flash('Monitoring completed — stream stopped, final status sent', 'success')
    except APIError as e:
        flash(e.message, 'error')
    return redirect(url_for('web.task_detail', receipt_token=receipt_token))


@web_bp.route('/receipts')
@login_required
def receipt_list():
    pguid = _get_provider_guid()
    receipts = SubmissionReceipt.query.filter_by(
        provider_guid=pguid
    ).order_by(SubmissionReceipt.submitted_at.desc()).all()
    return render_template('receipts.html', receipts=receipts)


@web_bp.route('/audit')
@login_required
def audit_log():
    pguid = _get_provider_guid()
    entries = TaskAuditLog.query.filter_by(
        provider_guid=pguid
    ).order_by(TaskAuditLog.created_at.desc()).limit(100).all()
    return render_template('audit.html', entries=entries)


@web_bp.route('/sync', methods=['POST'])
@login_required
def trigger_sync():
    from ..services.subscription import RequestSubscriptionService
    svc = RequestSubscriptionService(app=current_app._get_current_object())
    try:
        new, updated, skipped = svc.sync()
        flash(f'Sync complete: {new} new, {updated} updated, {skipped} unchanged', 'success')
    except Exception as e:
        flash(f'Sync failed: {e}', 'error')
    return redirect(url_for('web.dashboard'))


@web_bp.route('/gateway-receipts')
@login_required
def gateway_receipts():
    receipts = GatewayReceipt.query.order_by(GatewayReceipt.created_at.desc()).limit(200).all()
    return render_template('gateway_receipts.html', receipts=receipts)


@web_bp.route('/docs')
def docs_page():
    return render_template('docs.html')


@web_bp.route('/docs/download/<doc_name>')
def download_doc(doc_name):
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'docs')
    docs_dir = os.path.abspath(docs_dir)
    allowed = {
        'technical-guide': 'cgm_technical_guide.md',
    }
    filename = allowed.get(doc_name)
    if not filename:
        flash('Document not found', 'error')
        return redirect(url_for('web.docs_page'))
    filepath = os.path.join(docs_dir, filename)
    if not os.path.isfile(filepath):
        flash('Document file not found on server', 'error')
        return redirect(url_for('web.docs_page'))
    return send_file(filepath, as_attachment=True, download_name=filename)
