"""Maps upstream request.pdhc response format to local models.

Supports both:
- New format: FHIR ServiceRequest envelope from /provider/download
- Legacy format: flat dict from /requests
"""
from datetime import datetime, timezone


class RequestMapper:

    @staticmethod
    def from_feed_item(feed_item):
        """Map a feed metadata item to minimal InboundRequest fields."""
        return {
            'service_request_guid': feed_item['service_request_guid'],
            'match_guid': feed_item.get('match_guid'),
            'status': feed_item.get('status', 'pending'),
            'title': feed_item.get('title', ''),
            'intent': feed_item.get('intent'),
            'priority': feed_item.get('priority', 'routine'),
            'contract_guid': feed_item.get('contract_guid'),
            'download_url': feed_item.get('download_url'),
            'created_at': feed_item.get('created_at'),
            'updated_at': feed_item.get('updated_at'),
        }

    @staticmethod
    def from_downloaded_bundle(bundle_data, provider_guid, source_url=None):
        """Map a downloaded FHIR Bundle response to InboundRequest + ProviderTask."""
        from ..models import InboundRequest

        fhir = bundle_data.get('fhir_resource', {})
        sr_guid = bundle_data['service_request_guid']
        patient_guid = bundle_data.get('patient_guid')
        contract_guid = bundle_data.get('contract_guid')
        grant_token = bundle_data.get('grant_token')

        careplan = _extract_careplan(fhir)
        patient_name = _extract_patient_name(fhir)
        title = _extract_title(fhir, careplan)

        dispatched_at = None
        if fhir.get('authoredOn'):
            try:
                dispatched_at = datetime.fromisoformat(fhir['authoredOn'].replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass

        due_at = None
        occurrence = fhir.get('occurrencePeriod', {})
        if occurrence.get('end'):
            try:
                due_at = datetime.fromisoformat(occurrence['end'].replace('Z', '+00:00'))
            except (ValueError, TypeError):
                pass

        inbound_data = {
            'request_guid': sr_guid,
            'provider_guid': provider_guid,
            'receipt_token': sr_guid,
            'careplan_json': careplan,
            'fhir_resource': fhir,
            'patient_guid': patient_guid,
            'contract_guid': contract_guid,
            'grant_token': grant_token,
            'status': 'new',
            'source_url': source_url,
            'checksum': InboundRequest.compute_checksum(fhir),
        }

        task_data = {
            'receipt_token': sr_guid,
            'provider_guid': provider_guid,
            'request_guid': sr_guid,
            'status': 'dispatched',
            'patient_guid': patient_guid,
            'patient_name': patient_name,
            'careplan_guid': careplan.get('id') if careplan else None,
            'careplan_title': title,
            'dispatched_at': dispatched_at,
            'due_at': due_at,
            'priority': fhir.get('priority', 'routine'),
        }

        return inbound_data, task_data

    # ── Legacy mappers ─────────────────────────────────────

    @staticmethod
    def to_inbound_request(upstream_data, source_url=None):
        from ..models import InboundRequest
        careplan = upstream_data.get('careplan', {})
        return {
            'request_guid': upstream_data['request_guid'],
            'provider_guid': upstream_data['provider_guid'],
            'receipt_token': upstream_data['receipt_token'],
            'careplan_json': careplan,
            'status': 'new',
            'provider_status': upstream_data.get('provider_status'),
            'source_url': source_url,
            'checksum': InboundRequest.compute_checksum(careplan),
        }

    @staticmethod
    def to_provider_task(upstream_data):
        careplan = upstream_data.get('careplan', {})
        patient = careplan.get('patient', {})
        dispatch = careplan.get('dispatch_metadata', {})

        dispatched_at = None
        if dispatch.get('dispatched_at'):
            try:
                dispatched_at = datetime.fromisoformat(dispatch['dispatched_at'])
            except (ValueError, TypeError):
                pass

        due_at = None
        if dispatch.get('due_at'):
            try:
                due_at = datetime.fromisoformat(dispatch['due_at'])
            except (ValueError, TypeError):
                pass

        return {
            'receipt_token': upstream_data['receipt_token'],
            'provider_guid': upstream_data['provider_guid'],
            'request_guid': upstream_data['request_guid'],
            'status': 'dispatched',
            'patient_guid': patient.get('patient_guid'),
            'patient_name': patient.get('name'),
            'careplan_guid': careplan.get('careplan_guid'),
            'careplan_title': careplan.get('title'),
            'dispatched_at': dispatched_at,
            'due_at': due_at,
            'priority': dispatch.get('priority', 'routine'),
            'notes': dispatch.get('notes'),
        }

    @staticmethod
    def to_careplan_cache(upstream_data):
        careplan = upstream_data.get('careplan', {})
        return {
            'receipt_token': upstream_data['receipt_token'],
            'careplan_json': careplan,
        }


# ── FHIR extraction helpers ─────────────────────────────

def _extract_careplan(fhir_resource):
    """Extract CarePlan from FHIR ServiceRequest's contained resources."""
    for res in fhir_resource.get('contained', []):
        if res.get('resourceType') == 'CarePlan':
            return res
    return {}


def _extract_patient_name(fhir_resource):
    """Extract patient name from contained Patient resource."""
    for res in fhir_resource.get('contained', []):
        if res.get('resourceType') == 'Patient':
            names = res.get('name', [])
            if names:
                name = names[0]
                parts = name.get('given', []) + [name.get('family', '')]
                return ' '.join(p for p in parts if p)
    subject = fhir_resource.get('subject', {})
    return subject.get('display', '')


def _extract_title(fhir_resource, careplan):
    """Extract title from ServiceRequest or contained CarePlan."""
    if careplan and careplan.get('title'):
        return careplan['title']
    code = fhir_resource.get('code', {})
    if code.get('text'):
        return code['text']
    return ''
