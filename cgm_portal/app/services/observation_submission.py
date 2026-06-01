"""ObservationSubmissionService — continuous observation batch submission.

Handles the CGM-specific flow: submit multiple observation batches while
the task is in 'monitoring' status, then complete when done.
"""
import logging
from datetime import datetime, timezone
from ..models import ProviderTask, TaskAuditLog, ObservationLog, InboundRequest
from ..extensions import db
from ..errors import APIError

logger = logging.getLogger(__name__)


class ObservationSubmissionService:

    @staticmethod
    def submit_batch(receipt_token, provider_guid, observations):
        """Submit an observation batch to gateway. Task transitions to 'monitoring'.

        Can be called multiple times while task is acknowledged or monitoring.
        Returns (task, observation_log_entry).
        """
        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)

        if task.status not in ('acknowledged', 'monitoring'):
            raise APIError(
                f'Cannot submit observations for task in status: {task.status}',
                code='CONFLICT',
                status_code=409,
            )

        if not observations:
            raise APIError('observations array is required and must not be empty',
                           code='VALIDATION_ERROR', status_code=400)

        # Dedup check on raw input (before build_payload adds recorded_at)
        payload_hash = ObservationLog.hash_payload(observations)

        existing = ObservationLog.query.filter_by(
            receipt_token=receipt_token, payload_hash=payload_hash
        ).first()
        if existing:
            return task, existing  # idempotent

        # Build minimal payload for gateway
        from .guided_response import GuidedResponseService
        report_payload = GuidedResponseService.build_payload(observations)

        # Determine batch number
        batch_number = task.total_observations_submitted + 1

        # Submit to gateway via status callback. push_status returns a
        # bool — True only when the upstream HTTP call genuinely succeeded.
        # Previously this branch always set 'delivered' because push_status
        # swallowed its own exceptions internally and returned None, so
        # failures were silently logged as deliveries.
        gateway_status = 'pending'
        gateway_error = None
        try:
            from .status_callback import StatusCallbackService
            ok, err = StatusCallbackService.push_status(
                receipt_token, provider_guid, 'in-progress',
                report_payload=report_payload,
            )
            if ok:
                gateway_status = 'delivered'
            else:
                gateway_status = 'failed'
                gateway_error = err or 'upstream push failed'
        except Exception as e:
            gateway_status = 'failed'
            gateway_error = str(e)
            logger.warning('Failed to push observation batch %d for %s: %s',
                           batch_number, receipt_token, e)

        # Log the batch
        log_entry = ObservationLog(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            batch_number=batch_number,
            observation_count=len(observations),
            payload_hash=payload_hash,
            gateway_status=gateway_status,
            gateway_error=gateway_error,
        )
        db.session.add(log_entry)

        # Update task
        task.status = 'monitoring'
        task.last_observation_at = datetime.now(timezone.utc)
        task.total_observations_submitted = batch_number

        # Audit
        db.session.add(TaskAuditLog(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            action='observe',
            payload_snapshot={
                'batch_number': batch_number,
                'observation_count': len(observations),
                'gateway_status': gateway_status,
                'payload_hash': payload_hash,
            },
        ))

        db.session.commit()
        return task, log_entry

    @staticmethod
    def complete_monitoring(receipt_token, provider_guid, notes=None):
        """Mark monitoring as completed. Stops the auto-stream and sends
        final status='completed' to gateway.

        Returns the updated task.
        """
        # Stop the background glucose stream first
        try:
            from .observation_streamer import stop_stream
            stop_stream(receipt_token)
        except Exception:
            pass

        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)

        if task.status == 'completed':
            return task  # idempotent

        if task.status not in ('monitoring',):
            raise APIError(
                f'Cannot complete monitoring for task in status: {task.status}',
                code='CONFLICT',
                status_code=409,
            )

        task.status = 'completed'
        task.completed_at = datetime.now(timezone.utc)
        if notes:
            task.notes = notes

        # Send final completed status to gateway
        try:
            from .status_callback import StatusCallbackService
            summary_payload = {
                'monitoring_summary': {
                    'total_batches': task.total_observations_submitted,
                    'monitoring_started': task.acknowledged_at.isoformat() if task.acknowledged_at else None,
                    'monitoring_ended': task.completed_at.isoformat(),
                    'notes': notes,
                },
            }
            StatusCallbackService.push_status(
                receipt_token, provider_guid, 'completed',
                report_payload=summary_payload,
            )
        except Exception as e:
            logger.warning('Failed to push completion status for %s: %s', receipt_token, e)

        db.session.add(TaskAuditLog(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            action='report',
            payload_snapshot={
                'total_batches': task.total_observations_submitted,
                'notes': notes,
            },
        ))

        db.session.commit()
        return task

    @staticmethod
    def get_observation_log(receipt_token, provider_guid, limit=50):
        """Get observation batch log for a task."""
        return (
            ObservationLog.query
            .filter_by(receipt_token=receipt_token, provider_guid=provider_guid)
            .order_by(ObservationLog.batch_number.desc())
            .limit(limit)
            .all()
        )
