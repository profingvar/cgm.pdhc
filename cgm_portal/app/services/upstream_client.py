"""HTTP client for request.pdhc API.

Supports both:
- PAT auth (X-Provider-Token) — new provider delivery endpoints
- SSO API key (X-API-Key) — legacy fallback
"""
import logging
import requests as http_requests
from ..errors import APIError

logger = logging.getLogger(__name__)


class UpstreamClient:

    def __init__(self, base_url, provider_token=None, api_key=None):
        self.base_url = base_url.rstrip('/')
        self.session = http_requests.Session()
        self.session.headers['Accept'] = 'application/json'

        # Prefer PAT over legacy API key
        if provider_token:
            self.session.headers['X-Provider-Token'] = provider_token
            self.auth_mode = 'pat'
        elif api_key:
            self.session.headers['X-API-Key'] = api_key
            self.auth_mode = 'legacy'
        else:
            self.auth_mode = 'none'

    # ── New provider delivery endpoints ──────────────────────

    def fetch_feed(self, since=None, limit=50):
        """Fetch metadata-only feed of ServiceRequests for this provider."""
        params = {'limit': min(limit, 200)}
        if since:
            params['since'] = since.isoformat() if hasattr(since, 'isoformat') else since

        url = f'{self.base_url}/provider/feed'
        logger.info('Fetching provider feed from %s', url)

        resp = self.session.get(url, params=params, timeout=30)
        self._check_response(resp, 'feed')
        return resp.json()

    def download_bundle(self, service_request_guid):
        """Download the full FHIR Bundle + grant_token for a ServiceRequest."""
        url = f'{self.base_url}/provider/download/{service_request_guid}'
        logger.info('Downloading bundle for SR %s', service_request_guid)

        resp = self.session.get(url, timeout=30)
        self._check_response(resp, 'download')
        return resp.json()

    def submit_report(self, service_request_guid, patient_guid,
                      grant_token, status='completed', report_payload=None,
                      contract_guid=None, organisation_guid=None):
        """Submit a report back to gateway.pdhc using minimal payload."""
        url = f'{self.base_url}/provider/report/{service_request_guid}'
        body = {
            'patient_guid': patient_guid,
            'grant_token': grant_token,
            'status': status,
        }
        if contract_guid:
            body['contract_guid'] = contract_guid
        if organisation_guid:
            body['organisation_guid'] = organisation_guid
        if report_payload:
            body['report_payload'] = report_payload

        logger.info('Submitting report for SR %s (status=%s)', service_request_guid, status)

        resp = self.session.post(url, json=body, timeout=30)
        self._check_response(resp, 'report')
        return resp.json()

    def ack_receipt(self, receipt_token):
        """Acknowledge a push delivery receipt."""
        url = f'{self.base_url}/provider/receipt/{receipt_token}/ack'
        resp = self.session.post(url, json={'status': 'acknowledged'}, timeout=30)
        self._check_response(resp, 'receipt_ack')
        return resp.json()

    # ── Legacy endpoints (fallback) ──────────────────────────

    def fetch_requests(self, provider_guid, since=None, cursor=None, count=100):
        """Legacy: Fetch requests from old /requests endpoint."""
        params = {
            'provider_guid': provider_guid,
            '_count': min(count, 500),
        }
        if since:
            params['since'] = since.isoformat() if hasattr(since, 'isoformat') else since
        if cursor:
            params['cursor'] = cursor

        url = f'{self.base_url}/requests'
        logger.info('Fetching requests (legacy) from %s params=%s', url, params)

        resp = self.session.get(url, params=params, timeout=30)
        self._check_response(resp, 'legacy_fetch')
        return resp.json()

    def push_status(self, request_guid, provider_guid, status):
        """Legacy: Push provider status back via old /requests endpoint."""
        url = f'{self.base_url}/requests/{request_guid}/status'
        resp = self.session.put(
            url,
            json={'provider_guid': provider_guid, 'status': status},
            timeout=30,
        )
        if resp.status_code == 200:
            logger.info('Pushed status %s for request %s', status, request_guid)
            return resp.json()
        logger.warning(
            'Failed to push status %s for request %s: HTTP %d',
            status, request_guid, resp.status_code,
        )
        return None

    # ── Helpers ──────────────────────────────────────────────

    def _check_response(self, resp, operation):
        if resp.status_code == 401:
            raise APIError(
                f'Upstream auth failed on {operation}: invalid token',
                code='UPSTREAM_AUTH_FAILED', status_code=502,
            )
        if resp.status_code == 403:
            raise APIError(
                f'Upstream auth denied on {operation}: insufficient permissions',
                code='UPSTREAM_AUTH_DENIED', status_code=502,
            )
        if resp.status_code not in (200, 201, 202):
            raise APIError(
                f'Upstream error on {operation}: HTTP {resp.status_code}',
                code='UPSTREAM_ERROR', status_code=502,
            )
