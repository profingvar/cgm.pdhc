from ..models import ProviderTask, CarePlanCache
from ..extensions import db
from ..errors import APIError


class CarePlanDetailsService:

    @staticmethod
    def get_details(receipt_token, provider_guid):
        task = ProviderTask.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not task:
            raise APIError('Task not found', code='TASK_NOT_FOUND', status_code=404)

        cached = CarePlanCache.query.filter_by(receipt_token=receipt_token).first()
        if cached and not cached.is_stale():
            return cached.careplan_json

        raise APIError(
            'CarePlan details not available',
            code='CAREPLAN_NOT_FOUND',
            status_code=404,
        )

    @staticmethod
    def store_details(receipt_token, careplan_json):
        cached = CarePlanCache.query.filter_by(receipt_token=receipt_token).first()
        if cached:
            cached.careplan_json = careplan_json
            from datetime import datetime, timezone
            cached.fetched_at = datetime.now(timezone.utc)
        else:
            cached = CarePlanCache(
                receipt_token=receipt_token,
                careplan_json=careplan_json,
            )
            db.session.add(cached)
        db.session.commit()
        return cached
