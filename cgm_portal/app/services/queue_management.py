from ..models import ProviderTask
from ..extensions import db
from ..errors import APIError


class QueueManagementService:

    @staticmethod
    def set_active(receipt_token, provider_guid):
        ProviderTask.query.filter_by(
            provider_guid=provider_guid, is_active=True
        ).update({'is_active': False})

        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)
        task.is_active = True
        db.session.commit()
        return task

    @staticmethod
    def get_queue(provider_guid, active_only=False):
        query = ProviderTask.query.filter_by(provider_guid=provider_guid)
        if active_only:
            query = query.filter_by(is_active=True)
        return query.order_by(ProviderTask.created_at.desc()).all()

    @staticmethod
    def clear_queue(provider_guid):
        ProviderTask.query.filter_by(provider_guid=provider_guid).update({
            'is_active': False,
        })
        db.session.commit()
