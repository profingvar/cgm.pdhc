import uuid
import hashlib
import json
from datetime import datetime, timezone
from ..extensions import db


class SubmissionReceipt(db.Model):
    __tablename__ = 'submission_receipts'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    receipt_token = db.Column(db.String(255), nullable=False, index=True)
    provider_guid = db.Column(db.String(36), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=True)
    payload_hash = db.Column(db.String(64), nullable=True)
    submitted_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'receipt_token': self.receipt_token,
            'provider_guid': self.provider_guid,
            'status': self.status,
            'message': self.message,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }

    @staticmethod
    def hash_payload(payload):
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
