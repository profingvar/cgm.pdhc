"""Tests for continuous observation submission (CGM-specific)."""
import json
from unittest.mock import patch


def _create_task(db, provider, status='acknowledged'):
    from app.models import ProviderTask, InboundRequest
    task = ProviderTask(
        receipt_token='task-cgm-001',
        provider_guid=provider.guid,
        request_guid='sr-cgm-001',
        status=status,
        patient_guid='pat-001',
        careplan_title='CGM Glucose Monitoring',
    )
    db.session.add(task)

    inbound = InboundRequest(
        request_guid='sr-cgm-001',
        provider_guid=provider.guid,
        receipt_token='task-cgm-001',
        careplan_json={},
        patient_guid='pat-001',
        grant_token='test-grant-token',
        status='new',
        checksum='abc123',
    )
    db.session.add(inbound)
    db.session.commit()
    return task


def test_submit_observation_batch(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider)

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                           headers=auth_headers,
                           json={
                               'observations': [
                                   {'transaction_guid': 'tx-001', 'value': 5.6},
                                   {'transaction_guid': 'tx-001', 'value': 5.8},
                               ]
                           })
    assert resp.status_code == 202
    data = resp.get_json()
    assert data['batch_number'] == 1
    assert data['observation_count'] == 2
    assert data['task_status'] == 'monitoring'
    assert data['total_observations_submitted'] == 1


def test_submit_multiple_batches(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider)

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        # Batch 1
        resp1 = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                            headers=auth_headers,
                            json={'observations': [{'transaction_guid': 'tx-001', 'value': 5.6}]})
        assert resp1.status_code == 202
        assert resp1.get_json()['batch_number'] == 1

        # Batch 2
        resp2 = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                            headers=auth_headers,
                            json={'observations': [{'transaction_guid': 'tx-001', 'value': 6.1}]})
        assert resp2.status_code == 202
        assert resp2.get_json()['batch_number'] == 2
        assert resp2.get_json()['total_observations_submitted'] == 2


def test_idempotent_batch(client, provider, api_key, auth_headers, app):
    """Same payload submitted twice returns same batch without creating a duplicate."""
    from app.extensions import db
    _create_task(db, provider)
    payload = {'observations': [{'transaction_guid': 'tx-001', 'value': 5.6}]}

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        resp1 = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                            headers=auth_headers, json=payload)
        resp2 = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                            headers=auth_headers, json=payload)

    assert resp1.status_code == 202
    assert resp2.status_code == 202
    assert resp1.get_json()['batch_number'] == resp2.get_json()['batch_number']


def test_cannot_observe_dispatched_task(client, provider, api_key, auth_headers, app):
    """Cannot submit observations for a task that hasn't been acknowledged."""
    from app.extensions import db
    _create_task(db, provider, status='dispatched')

    resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                       headers=auth_headers,
                       json={'observations': [{'transaction_guid': 'tx-001', 'value': 5.6}]})
    assert resp.status_code == 409


def test_cannot_observe_completed_task(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider, status='completed')

    resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                       headers=auth_headers,
                       json={'observations': [{'transaction_guid': 'tx-001', 'value': 5.6}]})
    assert resp.status_code == 409


def test_complete_monitoring(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider, status='monitoring')

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe/complete',
                           headers=auth_headers,
                           json={'notes': 'Monitoring period ended normally'})

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'completed'
    assert data['completed_at'] is not None


def test_cannot_complete_non_monitoring_task(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider, status='acknowledged')

    resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe/complete',
                       headers=auth_headers, json={})
    assert resp.status_code == 409


def test_observation_log(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider)

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                    headers=auth_headers,
                    json={'observations': [{'transaction_guid': 'tx-001', 'value': 5.6}]})
        client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                    headers=auth_headers,
                    json={'observations': [{'transaction_guid': 'tx-001', 'value': 6.1}]})

    resp = client.get('/api/v1/provider-tasks/task-cgm-001/observe/log',
                      headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 2
    assert data[0]['batch_number'] == 2  # desc order
    assert data[1]['batch_number'] == 1


def test_empty_observations_rejected(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider)

    resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                       headers=auth_headers,
                       json={'observations': []})
    assert resp.status_code == 400


def test_missing_observations_key_rejected(client, provider, api_key, auth_headers, app):
    from app.extensions import db
    _create_task(db, provider)

    resp = client.post('/api/v1/provider-tasks/task-cgm-001/observe',
                       headers=auth_headers,
                       json={'data': 'invalid'})
    assert resp.status_code == 400
