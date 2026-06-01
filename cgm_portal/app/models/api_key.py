import uuid
from datetime import datetime, timezone
import bcrypt
from ..extensions import db


class ApiKey(db.Model):
    __tablename__ = 'api_keys'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    provider_guid = db.Column(db.String(36), db.ForeignKey('providers.guid'), nullable=False, index=True)
    key_hash = db.Column(db.String(255), nullable=False)
    scopes = db.Column(db.String(255), nullable=False, default='read')
    label = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    revoked = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(cls, provider_guid, raw_key, scopes='read', label=None, expires_at=None):
        key_hash = bcrypt.hashpw(raw_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        return cls(
            provider_guid=provider_guid,
            key_hash=key_hash,
            scopes=scopes,
            label=label,
            expires_at=expires_at,
        )

    def verify(self, raw_key):
        return bcrypt.checkpw(raw_key.encode('utf-8'), self.key_hash.encode('utf-8'))

    def is_valid(self):
        if self.revoked:
            return False
        if self.expires_at:
            expires = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > expires:
                return False
        return True

    def has_scope(self, scope):
        return scope in self.scopes.split(',')
