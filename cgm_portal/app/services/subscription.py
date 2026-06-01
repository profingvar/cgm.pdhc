"""RequestSubscriptionService — syncs requests from request.pdhc.

Two-step sync (GDPR data minimization):
1. Fetch metadata-only feed (no patient data)
2. Download full FHIR Bundle for each new/updated item
"""
import logging
from datetime import datetime, timezone
from ..models import InboundRequest, SyncState, ProviderTask, CarePlanCache, TaskAuditLog
from ..extensions import db
from .request_mapper import RequestMapper
from .upstream_client import UpstreamClient

logger = logging.getLogger(__name__)


class RequestSubscriptionService:

    def __init__(self, app=None):
        self.app = app
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = UpstreamClient(
                base_url=self.app.config['REQUEST_SERVICE_URL'],
                provider_token=self.app.config.get('PROVIDER_TOKEN'),
                api_key=self.app.config.get('SSO_API_KEY'),
            )
        return self._client

    def sync(self):
        """Run one sync cycle. Returns (new_count, updated_count, skipped_count)."""
        provider_guid = self.app.config['PROVIDER_GUID']
        if not provider_guid:
            logger.warning('PROVIDER_GUID not configured, skipping sync')
            return 0, 0, 0

        state = self._get_or_create_state(provider_guid)

        if self.app.config.get('PROVIDER_TOKEN'):
            return self._sync_via_feed(state, provider_guid)
        else:
            return self._sync_legacy(state, provider_guid)

    def _sync_via_feed(self, state, provider_guid):
        """Two-step sync: metadata feed → selective download."""
        new_count = 0
        updated_count = 0
        skipped_count = 0

        try:
            feed_data = self.client.fetch_feed(since=state.last_sync_at)
            items = feed_data.get('items', [])

            for item in items:
                sr_guid = item['service_request_guid']
                existing = InboundRequest.query.filter_by(request_guid=sr_guid).first()

                if existing and existing.status in ('completed',):
                    skipped_count += 1
                    continue

                try:
                    bundle_data = self.client.download_bundle(sr_guid)
                except Exception as e:
                    logger.warning('Failed to download bundle for %s: %s', sr_guid, e)
                    continue

                result = self._process_bundle(bundle_data, provider_guid, existing)
                if result == 'new':
                    new_count += 1
                elif result == 'updated':
                    updated_count += 1
                else:
                    skipped_count += 1

            state.last_sync_at = datetime.now(timezone.utc)
            state.requests_synced += new_count
            state.last_error = None
            db.session.commit()

            logger.info('Sync (feed) complete: %d new, %d updated, %d skipped',
                        new_count, updated_count, skipped_count)

        except Exception as e:
            logger.error('Sync failed: %s', str(e))
            state.last_error = str(e)
            db.session.commit()
            raise

        return new_count, updated_count, skipped_count

    def _process_bundle(self, bundle_data, provider_guid, existing):
        """Process a downloaded FHIR bundle into InboundRequest + ProviderTask."""
        inbound_data, task_data = RequestMapper.from_downloaded_bundle(
            bundle_data,
            provider_guid=provider_guid,
            source_url=self.app.config['REQUEST_SERVICE_URL'],
        )

        sr_guid = inbound_data['request_guid']

        if existing:
            if existing.checksum == inbound_data['checksum']:
                existing.last_synced_at = datetime.now(timezone.utc)
                db.session.flush()
                return 'skipped'

            existing.careplan_json = inbound_data['careplan_json']
            existing.fhir_resource = inbound_data['fhir_resource']
            existing.checksum = inbound_data['checksum']
            existing.grant_token = inbound_data['grant_token']
            existing.patient_guid = inbound_data['patient_guid']
            existing.contract_guid = inbound_data['contract_guid']
            existing.last_synced_at = datetime.now(timezone.utc)

            self._update_careplan_cache(sr_guid, inbound_data['careplan_json'])

            db.session.add(TaskAuditLog(
                receipt_token=existing.receipt_token,
                provider_guid=provider_guid,
                action='sync',
                payload_snapshot={
                    'request_guid': sr_guid,
                    'checksum': inbound_data['checksum'],
                    'is_new': False,
                    'auth_mode': 'pat',
                },
            ))
            db.session.flush()
            return 'updated'

        inbound = InboundRequest(**inbound_data)
        db.session.add(inbound)

        existing_task = ProviderTask.query.filter_by(receipt_token=task_data['receipt_token']).first()
        if not existing_task:
            task = ProviderTask(**task_data)
            db.session.add(task)

        self._update_careplan_cache(sr_guid, inbound_data['careplan_json'])

        db.session.add(TaskAuditLog(
            receipt_token=inbound_data['receipt_token'],
            provider_guid=provider_guid,
            action='sync',
            payload_snapshot={
                'request_guid': sr_guid,
                'checksum': inbound_data['checksum'],
                'is_new': True,
                'auth_mode': 'pat',
            },
        ))
        db.session.flush()
        return 'new'

    # ── Legacy sync ────────────────────────────────────────

    def _sync_legacy(self, state, provider_guid):
        """Original sync via /requests endpoint with SSO API key."""
        new_count = 0
        updated_count = 0
        skipped_count = 0
        cursor = None

        try:
            while True:
                data = self.client.fetch_requests(
                    provider_guid=provider_guid,
                    since=state.last_sync_at,
                    cursor=cursor,
                )
                requests_list = data.get('requests', [])

                for req_data in requests_list:
                    if req_data.get('provider_guid') != provider_guid:
                        continue

                    result = self._process_legacy_request(req_data, provider_guid)
                    if result == 'new':
                        new_count += 1
                    elif result == 'updated':
                        updated_count += 1
                    else:
                        skipped_count += 1

                cursor = data.get('cursor')
                if not data.get('has_more'):
                    break

            state.last_sync_at = datetime.now(timezone.utc)
            state.last_sync_cursor = cursor
            state.requests_synced += new_count
            state.last_error = None
            db.session.commit()

            logger.info('Sync (legacy) complete: %d new, %d updated, %d skipped',
                        new_count, updated_count, skipped_count)

        except Exception as e:
            logger.error('Sync failed: %s', str(e))
            state.last_error = str(e)
            db.session.commit()
            raise

        return new_count, updated_count, skipped_count

    def _process_legacy_request(self, req_data, provider_guid):
        """Process a single upstream request (legacy format)."""
        request_guid = req_data['request_guid']
        mapped = RequestMapper.to_inbound_request(
            req_data,
            source_url=self.app.config['REQUEST_SERVICE_URL'],
        )

        existing = InboundRequest.query.filter_by(request_guid=request_guid).first()

        if existing:
            if existing.checksum == mapped['checksum']:
                existing.last_synced_at = datetime.now(timezone.utc)
                db.session.flush()
                return 'skipped'

            existing.careplan_json = mapped['careplan_json']
            existing.checksum = mapped['checksum']
            existing.provider_status = mapped['provider_status']
            existing.last_synced_at = datetime.now(timezone.utc)

            self._update_careplan_cache_legacy(req_data)

            db.session.add(TaskAuditLog(
                receipt_token=existing.receipt_token,
                provider_guid=provider_guid,
                action='sync',
                payload_snapshot={
                    'request_guid': request_guid,
                    'checksum': mapped['checksum'],
                    'is_new': False,
                },
            ))
            db.session.flush()
            return 'updated'

        inbound = InboundRequest(**mapped)
        db.session.add(inbound)

        task_data = RequestMapper.to_provider_task(req_data)
        existing_task = ProviderTask.query.filter_by(receipt_token=task_data['receipt_token']).first()
        if not existing_task:
            task = ProviderTask(**task_data)
            db.session.add(task)

        self._update_careplan_cache_legacy(req_data)

        db.session.add(TaskAuditLog(
            receipt_token=mapped['receipt_token'],
            provider_guid=provider_guid,
            action='sync',
            payload_snapshot={
                'request_guid': request_guid,
                'checksum': mapped['checksum'],
                'is_new': True,
            },
        ))
        db.session.flush()
        return 'new'

    # ── Cache helpers ────────────────────────────────────────

    def _update_careplan_cache(self, receipt_token, careplan_json):
        cached = CarePlanCache.query.filter_by(receipt_token=receipt_token).first()
        if cached:
            cached.careplan_json = careplan_json
            cached.fetched_at = datetime.now(timezone.utc)
        else:
            cached = CarePlanCache(
                receipt_token=receipt_token,
                careplan_json=careplan_json,
            )
            db.session.add(cached)

    def _update_careplan_cache_legacy(self, req_data):
        cache_data = RequestMapper.to_careplan_cache(req_data)
        self._update_careplan_cache(cache_data['receipt_token'], cache_data['careplan_json'])

    def _get_or_create_state(self, provider_guid):
        state = SyncState.query.filter_by(provider_guid=provider_guid).first()
        if not state:
            state = SyncState(provider_guid=provider_guid, requests_synced=0)
            db.session.add(state)
            db.session.flush()
        return state

    def get_status(self):
        provider_guid = self.app.config.get('PROVIDER_GUID')
        if not provider_guid:
            return {'configured': False}
        state = SyncState.query.filter_by(provider_guid=provider_guid).first()
        result = {
            'configured': True,
            'provider_guid': provider_guid,
            'provider_name': self.app.config.get('PROVIDER_NAME'),
            'sync_enabled': self.app.config.get('SYNC_ENABLED', False),
            'request_service_url': self.app.config.get('REQUEST_SERVICE_URL'),
            'auth_mode': 'pat' if self.app.config.get('PROVIDER_TOKEN') else 'legacy',
        }
        if state:
            result.update(state.to_dict())
        return result
