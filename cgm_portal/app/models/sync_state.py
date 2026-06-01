from datetime import datetime, timezone
from ..extensions import db


class SyncState(db.Model):
    __tablename__ = 'sync_state'

    id = db.Column(db.Integer, primary_key=True)
    provider_guid = db.Column(db.String(36), unique=True, nullable=False)
    last_sync_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_sync_cursor = db.Column(db.String(255), nullable=True)
    requests_synced = db.Column(db.Integer, default=0, nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'provider_guid': self.provider_guid,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
            'last_sync_cursor': self.last_sync_cursor,
            'requests_synced': self.requests_synced,
            'last_error': self.last_error,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
