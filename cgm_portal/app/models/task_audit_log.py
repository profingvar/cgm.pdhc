import uuid
from datetime import datetime, timezone
from ..extensions import db


class TaskAuditLog(db.Model):
    __tablename__ = 'task_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    receipt_token = db.Column(db.String(255), nullable=False, index=True)
    provider_guid = db.Column(db.String(36), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    payload_snapshot = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    VALID_ACTIONS = ('acknowledge', 'report', 'observe', 'sync')

    def to_dict(self):
        return {
            'guid': self.guid,
            'receipt_token': self.receipt_token,
            'provider_guid': self.provider_guid,
            'action': self.action,
            'payload_snapshot': self.payload_snapshot,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
