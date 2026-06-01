"""ObservationLog — tracks each observation batch submitted to gateway.

CGM providers submit multiple observation batches over a monitoring period.
Each batch is logged here for audit, deduplication, and status tracking.
"""
import uuid
import hashlib
import json
from datetime import datetime, timezone
from ..extensions import db


class ObservationLog(db.Model):
    __tablename__ = 'observation_log'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    receipt_token = db.Column(db.String(255), nullable=False, index=True)
    provider_guid = db.Column(db.String(36), nullable=False, index=True)
    batch_number = db.Column(db.Integer, nullable=False)
    observation_count = db.Column(db.Integer, nullable=False, default=0)
    payload_hash = db.Column(db.String(64), nullable=True)
    gateway_status = db.Column(db.String(50), nullable=False, default='pending')
    gateway_error = db.Column(db.Text, nullable=True)
    gateway_receipt_guid = db.Column(db.String(36), nullable=True)
    submitted_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    VALID_STATUSES = ('pending', 'delivered', 'failed')

    @staticmethod
    def hash_payload(payload):
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def to_dict(self):
        return {
            'guid': self.guid,
            'receipt_token': self.receipt_token,
            'provider_guid': self.provider_guid,
            'batch_number': self.batch_number,
            'observation_count': self.observation_count,
            'payload_hash': self.payload_hash,
            'gateway_status': self.gateway_status,
            'gateway_error': self.gateway_error,
            'gateway_receipt_guid': self.gateway_receipt_guid,
            'submitted_at': self.submitted_at.isoformat() if self.submitted_at else None,
        }
