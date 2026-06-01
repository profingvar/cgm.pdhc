import uuid
from datetime import datetime, timezone
from ..extensions import db


class Provider(db.Model):
    __tablename__ = 'providers'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    api_keys = db.relationship('ApiKey', backref='provider', lazy='dynamic',
                               foreign_keys='ApiKey.provider_guid',
                               primaryjoin='Provider.guid == ApiKey.provider_guid')

    def to_dict(self):
        return {
            'guid': self.guid,
            'name': self.name,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
