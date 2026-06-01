import uuid
from datetime import datetime, timezone
from ..extensions import db


class ProviderTask(db.Model):
    __tablename__ = 'provider_tasks'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    receipt_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    provider_guid = db.Column(db.String(36), db.ForeignKey('providers.guid'), nullable=False, index=True)
    status = db.Column(db.String(50), nullable=False, default='dispatched')
    is_active = db.Column(db.Boolean, default=False, nullable=False)

    # Patient/careplan summary
    patient_guid = db.Column(db.String(36), nullable=True)
    patient_name = db.Column(db.String(255), nullable=True)
    careplan_guid = db.Column(db.String(64), nullable=True)
    careplan_title = db.Column(db.String(255), nullable=True)

    # Dispatch metadata
    dispatched_at = db.Column(db.DateTime(timezone=True), nullable=True)
    due_at = db.Column(db.DateTime(timezone=True), nullable=True)
    acknowledged_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Upstream linkage
    request_guid = db.Column(db.String(36), nullable=True, index=True)
    priority = db.Column(db.String(20), nullable=True, default='routine')

    # Payload
    notes = db.Column(db.Text, nullable=True)

    # CGM monitoring fields
    monitoring_interval_seconds = db.Column(db.Integer, nullable=True)
    monitoring_until = db.Column(db.DateTime(timezone=True), nullable=True)
    last_observation_at = db.Column(db.DateTime(timezone=True), nullable=True)
    total_observations_submitted = db.Column(db.Integer, default=0, nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    VALID_STATUSES = ('dispatched', 'acknowledged', 'monitoring', 'completed', 'cancelled')

    def to_dict(self):
        return {
            'guid': self.guid,
            'receipt_token': self.receipt_token,
            'provider_guid': self.provider_guid,
            'status': self.status,
            'is_active': self.is_active,
            'patient_guid': self.patient_guid,
            'patient_name': self.patient_name,
            'careplan_guid': self.careplan_guid,
            'careplan_title': self.careplan_title,
            'dispatched_at': self.dispatched_at.isoformat() if self.dispatched_at else None,
            'due_at': self.due_at.isoformat() if self.due_at else None,
            'acknowledged_at': self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'request_guid': self.request_guid,
            'priority': self.priority,
            'notes': self.notes,
            'monitoring_interval_seconds': self.monitoring_interval_seconds,
            'monitoring_until': self.monitoring_until.isoformat() if self.monitoring_until else None,
            'last_observation_at': self.last_observation_at.isoformat() if self.last_observation_at else None,
            'total_observations_submitted': self.total_observations_submitted,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
