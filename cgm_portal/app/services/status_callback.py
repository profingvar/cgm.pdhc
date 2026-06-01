"""Pushes provider status/reports back to request.pdhc.

Uses composite key (PAT + grant_token) for the new API,
with fallback to legacy status push for old-format requests.
"""
import logging
from flask import current_app
from ..models import ProviderTask, InboundRequest
from .upstream_client import UpstreamClient

logger = logging.getLogger(__name__)


class StatusCallbackService:

    @staticmethod
    def push_status(receipt_token, provider_guid, status, report_payload=None):
        """Push status to upstream. Returns (ok, err_or_None).

        Uses composite key if grant_token available, falls back to legacy.
        """
        provider_token = current_app.config.get('PROVIDER_TOKEN')
        sso_key = current_app.config.get('SSO_API_KEY')
        base_url = current_app.config.get('REQUEST_SERVICE_URL')
        if not base_url:
            return False, 'REQUEST_SERVICE_URL not configured'

        inbound = InboundRequest.query.filter_by(
            receipt_token=receipt_token, provider_guid=provider_guid
        ).first()
        if not inbound:
            return False, 'no matching inbound_request (locally created task)'

        if provider_token and inbound.grant_token and inbound.patient_guid:
            return StatusCallbackService._push_via_composite_key(
                base_url, provider_token, inbound, provider_guid,
                status, report_payload,
            )
        elif sso_key:
            return StatusCallbackService._push_legacy(
                base_url, sso_key, inbound, provider_guid, status,
            )
        return False, 'no usable auth (PAT+grant or legacy SSO key)'

    @staticmethod
    def _push_via_composite_key(base_url, provider_token, inbound,
                                 provider_guid, status, report_payload=None):
        """Submit report via POST /provider/report/<sr_guid> with minimal payload."""
        try:
            client = UpstreamClient(base_url=base_url, provider_token=provider_token)
            result = client.submit_report(
                service_request_guid=inbound.request_guid,
                patient_guid=inbound.patient_guid,
                grant_token=inbound.grant_token,
                status=status,
                report_payload=report_payload,
            )
            if result:
                inbound.provider_status = status
                from ..extensions import db
                db.session.commit()
                logger.info('Submitted report for %s via composite key → %s',
                            inbound.request_guid, status)
                return True, None
            return False, 'upstream returned no result'
        except Exception as e:
            logger.warning('Failed to submit report for %s: %s',
                           inbound.request_guid, str(e))
            return False, str(e)

    @staticmethod
    def _push_legacy(base_url, sso_key, inbound, provider_guid, status):
        """Legacy: push simple status via PUT /requests/<guid>/status."""
        try:
            client = UpstreamClient(base_url=base_url, api_key=sso_key)
            result = client.push_status(
                request_guid=inbound.request_guid,
                provider_guid=provider_guid,
                status=status,
            )
            if result:
                inbound.provider_status = status
                from ..extensions import db
                db.session.commit()
                logger.info('Pushed status %s for %s to upstream (legacy)',
                            status, inbound.receipt_token)
                return True, None
            return False, 'upstream returned no result'
        except Exception as e:
            logger.warning('Failed to push status to upstream for %s: %s',
                           inbound.request_guid, str(e))
            return False, str(e)
