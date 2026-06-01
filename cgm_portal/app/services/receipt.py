from ..models import SubmissionReceipt
from ..errors import APIError


class ReceiptService:

    @staticmethod
    def get_receipts(provider_guid, receipt_token=None, limit=50):
        query = SubmissionReceipt.query.filter_by(provider_guid=provider_guid)
        if receipt_token:
            query = query.filter_by(receipt_token=receipt_token)
        return query.order_by(SubmissionReceipt.submitted_at.desc()).limit(limit).all()

    @staticmethod
    def get_receipt_by_guid(guid, provider_guid):
        receipt = SubmissionReceipt.query.filter_by(guid=guid, provider_guid=provider_guid).first()
        if not receipt:
            raise APIError('Receipt not found', code='RECEIPT_NOT_FOUND', status_code=404)
        return receipt
