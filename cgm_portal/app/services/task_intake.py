from ..models import ProviderTask
from ..extensions import db
from ..errors import APIError


class TaskIntakeService:

    @staticmethod
    def get_by_receipt_token(receipt_token, provider_guid):
        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token,
            provider_guid=provider_guid,
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)
        return task

    @staticmethod
    def list_tasks(provider_guid, status=None, limit=50):
        query = ProviderTask.query.filter_by(provider_guid=provider_guid)
        if status:
            query = query.filter_by(status=status)
        query = query.order_by(ProviderTask.created_at.desc())
        if limit:
            query = query.limit(limit)
        return query.all()

    @staticmethod
    def upsert_task(provider_guid, receipt_token, data):
        task = ProviderTask.query.filter_by(receipt_token=receipt_token).first()
        if task:
            if task.provider_guid != provider_guid:
                raise APIError('Task belongs to another provider', code='AUTH_SCOPE_MISMATCH', status_code=403)
            for key in ('status', 'patient_guid', 'patient_name', 'careplan_guid',
                        'careplan_title', 'dispatched_at', 'due_at', 'notes'):
                if key in data:
                    setattr(task, key, data[key])
        else:
            task = ProviderTask(
                receipt_token=receipt_token,
                provider_guid=provider_guid,
                status=data.get('status', 'dispatched'),
                patient_guid=data.get('patient_guid'),
                patient_name=data.get('patient_name'),
                careplan_guid=data.get('careplan_guid'),
                careplan_title=data.get('careplan_title'),
                dispatched_at=data.get('dispatched_at'),
                due_at=data.get('due_at'),
                notes=data.get('notes'),
            )
            db.session.add(task)
        db.session.commit()
        return task
