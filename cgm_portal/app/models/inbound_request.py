import uuid
import hashlib
import json
from datetime import datetime, timezone
from ..extensions import db


class InboundRequest(db.Model):
    __tablename__ = 'inbound_requests'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    request_guid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    provider_guid = db.Column(db.String(36), nullable=False, index=True)
    receipt_token = db.Column(db.String(255), nullable=False, index=True)
    careplan_json = db.Column(db.JSON, nullable=False)
    fhir_resource = db.Column(db.JSON, nullable=True)
    patient_guid = db.Column(db.String(36), nullable=True, index=True)
    contract_guid = db.Column(db.String(36), nullable=True)
    organisation_guid = db.Column(db.String(36), nullable=True, index=True)
    grant_token = db.Column(db.String(128), nullable=True)
    grant_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(50), nullable=False, default='new')
    provider_status = db.Column(db.String(50), nullable=True)
    source_url = db.Column(db.String(512), nullable=True)
    checksum = db.Column(db.String(64), nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_synced_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    VALID_STATUSES = ('new', 'synced', 'acknowledged', 'completed')

    @staticmethod
    def compute_checksum(careplan_json):
        return hashlib.sha256(json.dumps(careplan_json, sort_keys=True).encode()).hexdigest()

    def to_dict(self):
        return {
            'guid': self.guid,
            'request_guid': self.request_guid,
            'provider_guid': self.provider_guid,
            'receipt_token': self.receipt_token,
            'status': self.status,
            'provider_status': self.provider_status,
            'checksum': self.checksum,
            'received_at': self.received_at.isoformat() if self.received_at else None,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None,
        }
