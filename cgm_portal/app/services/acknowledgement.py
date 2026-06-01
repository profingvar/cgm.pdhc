import logging
from datetime import datetime, timezone
from flask import current_app
from ..models import ProviderTask, TaskAuditLog, CarePlanCache
from ..extensions import db
from ..errors import APIError

logger = logging.getLogger(__name__)


class AcknowledgementService:

    @staticmethod
    def acknowledge(receipt_token, provider_guid, notes=None):
        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)

        if task.status == 'acknowledged':
            return task  # idempotent

        if task.status not in ('dispatched',):
            raise APIError(
                f'Cannot acknowledge task in status: {task.status}',
                code='CONFLICT',
                status_code=409,
            )

        task.status = 'acknowledged'
        task.acknowledged_at = datetime.now(timezone.utc)
        if notes:
            task.notes = notes

        audit = TaskAuditLog(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            action='acknowledge',
            payload_snapshot={'notes': notes},
        )
        db.session.add(audit)
        db.session.commit()

        # Push status back to request.pdhc.se
        try:
            from .status_callback import StatusCallbackService
            StatusCallbackService.push_status(receipt_token, provider_guid, 'acknowledged')
        except Exception:
            pass

        # Auto-start glucose stream (non-blocking)
        if not current_app.config.get('TESTING'):
            try:
                tx_guid = _resolve_transaction_guid(receipt_token)
                from .observation_streamer import start_stream
                start_stream(
                    app=current_app._get_current_object(),
                    receipt_token=receipt_token,
                    provider_guid=provider_guid,
                    transaction_guid=tx_guid,
                    interval_seconds=60,
                )
                logger.info('Auto-started glucose stream for %s', receipt_token)
            except Exception as e:
                logger.warning('Failed to auto-start stream for %s: %s', receipt_token, e)

        return task


def _resolve_transaction_guid(receipt_token):
    """Try to find the first transaction_guid from the cached careplan.

    Falls back to a sensible default if no careplan is cached.
    """
    cached = CarePlanCache.query.filter_by(receipt_token=receipt_token).first()
    if cached and cached.careplan_json:
        cp = cached.careplan_json
        for activity in cp.get('activity', []):
            detail = activity.get('detail', {})
            for ext in detail.get('extension', []):
                txs = ext.get('_pdhc_transactions', [])
                for tx in txs:
                    if tx.get('transaction_guid'):
                        return tx['transaction_guid']
            # Also check flat transactions list (common format)
        if cp.get('_pdhc_transactions'):
            for tx in cp['_pdhc_transactions']:
                if tx.get('transaction_guid'):
                    return tx['transaction_guid']
    return 'tx-glucose'
