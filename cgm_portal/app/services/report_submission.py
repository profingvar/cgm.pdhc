from datetime import datetime, timezone
from ..models import ProviderTask, TaskAuditLog, SubmissionReceipt
from ..extensions import db
from ..errors import APIError


class ReportSubmissionService:

    @staticmethod
    def submit(receipt_token, provider_guid, provider_payload, notes=None, receipt_message=None):
        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)

        # Idempotency: check for duplicate payload
        payload_hash = SubmissionReceipt.hash_payload(provider_payload)
        existing = SubmissionReceipt.query.filter_by(
            receipt_token=receipt_token, payload_hash=payload_hash
        ).first()
        if existing:
            return task, existing  # idempotent

        if task.status == 'completed':
            raise APIError(
                'Task already completed',
                code='CONFLICT',
                status_code=409,
            )

        if task.status not in ('dispatched', 'acknowledged', 'monitoring'):
            raise APIError(
                f'Cannot submit report for task in status: {task.status}',
                code='CONFLICT',
                status_code=409,
            )

        task.status = 'completed'
        task.completed_at = datetime.now(timezone.utc)

        receipt = SubmissionReceipt(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            status='submitted',
            message=receipt_message or 'Report submitted successfully',
            payload_hash=payload_hash,
        )
        db.session.add(receipt)

        audit = TaskAuditLog(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            action='report',
            payload_snapshot={
                'provider_payload_hash': payload_hash,
                'notes': notes,
            },
        )
        db.session.add(audit)
        db.session.commit()

        # Push report back to request.pdhc via composite key
        try:
            from .status_callback import StatusCallbackService
            StatusCallbackService.push_status(
                receipt_token, provider_guid, 'completed',
                report_payload=provider_payload,
            )
        except Exception:
            pass  # don't fail the local operation if upstream push fails

        return task, receipt
