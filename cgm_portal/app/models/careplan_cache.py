from datetime import datetime, timezone
from ..extensions import db


class CarePlanCache(db.Model):
    __tablename__ = 'careplan_cache'

    id = db.Column(db.Integer, primary_key=True)
    receipt_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    careplan_json = db.Column(db.JSON, nullable=False)
    fetched_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ttl_seconds = db.Column(db.Integer, default=3600)

    def is_stale(self):
        if not self.fetched_at:
            return True
        fetched = self.fetched_at if self.fetched_at.tzinfo else self.fetched_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - fetched).total_seconds()
        return elapsed > self.ttl_seconds
