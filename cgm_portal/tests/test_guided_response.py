"""Tests for GuidedResponseService (observation validation + payload building)."""
import pytest
from app.services import GuidedResponseService
from app.errors import APIError


TRANSACTIONS = [
    {
        'transaction_guid': 'tx-001',
        'concept_guid': 'c-001',
        'concept_name': 'Blood Glucose',
        'response_type': 'numeric',
        'required': True,
    },
    {
        'transaction_guid': 'tx-002',
        'concept_guid': 'c-002',
        'concept_name': 'Trend',
        'response_type': 'categorical',
        'valueset_values': ['rising', 'stable', 'falling'],
        'required': False,
    },
]


def test_valid_observations(app):
    with app.app_context():
        observations = [
            {'transaction_guid': 'tx-001', 'value': 5.6},
        ]
        GuidedResponseService.validate_observations(observations, TRANSACTIONS)


def test_missing_required(app):
    with app.app_context():
        observations = [
            {'transaction_guid': 'tx-002', 'value': 'stable'},
        ]
        with pytest.raises(APIError) as exc_info:
            GuidedResponseService.validate_observations(observations, TRANSACTIONS)
        assert exc_info.value.status_code == 422
        assert any(d['transaction_guid'] == 'tx-001' for d in exc_info.value.details)


def test_invalid_categorical(app):
    with app.app_context():
        observations = [
            {'transaction_guid': 'tx-001', 'value': 5.6},
            {'transaction_guid': 'tx-002', 'value': 'crashing'},
        ]
        with pytest.raises(APIError) as exc_info:
            GuidedResponseService.validate_observations(observations, TRANSACTIONS)
        assert exc_info.value.status_code == 422


def test_build_payload(app):
    with app.app_context():
        observations = [
            {'transaction_guid': 'tx-001', 'value': 5.6, 'notes': 'Fasting'},
        ]
        result = GuidedResponseService.build_payload(observations)
        assert len(result['observations']) == 1
        obs = result['observations'][0]
        assert obs['transaction_guid'] == 'tx-001'
        assert obs['value'] == 5.6
        assert obs['notes'] == 'Fasting'
        assert obs['recorded_at'] is not None
        assert 'concept_guid' not in obs
        assert 'unit' not in obs


def test_build_payload_minimal(app):
    """Payload without notes omits the field entirely."""
    with app.app_context():
        observations = [
            {'transaction_guid': 'tx-001', 'value': 5.6},
        ]
        result = GuidedResponseService.build_payload(observations)
        obs = result['observations'][0]
        assert 'notes' not in obs
