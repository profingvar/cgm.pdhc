"""GatewayReceipt — stores observation receipts pushed from gateway.pdhc.

When gateway.pdhc accepts an observation report from cgm.pdhc, it pushes
a receipt back via POST /api/v1/receipts/ingest confirming how many observations
were stored and the payload hash.
"""
import uuid
from datetime import datetime, timezone
from ..extensions import db


class GatewayReceipt(db.Model):
    __tablename__ = 'gateway_receipts'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    receipt_guid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    service_request_guid = db.Column(db.String(36), nullable=False, index=True)
    patient_guid = db.Column(db.String(36), nullable=True, index=True)
    provider_org_guid = db.Column(db.String(36), nullable=True)
    contract_guid = db.Column(db.String(36), nullable=True)
    observations_stored = db.Column(db.Integer, nullable=False, default=0)
    accepted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    payload_hash = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'guid': self.guid,
            'receipt_guid': self.receipt_guid,
            'service_request_guid': self.service_request_guid,
            'patient_guid': self.patient_guid,
            'provider_org_guid': self.provider_org_guid,
            'contract_guid': self.contract_guid,
            'observations_stored': self.observations_stored,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'payload_hash': self.payload_hash,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
