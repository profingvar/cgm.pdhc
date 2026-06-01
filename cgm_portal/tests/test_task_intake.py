"""Tests for task listing and retrieval."""
import json


def test_list_empty_tasks(client, api_key, auth_headers):
    resp = client.get('/api/v1/provider-tasks/my', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_get_nonexistent_task(client, api_key, auth_headers):
    resp = client.get('/api/v1/provider-tasks/nonexistent', headers=auth_headers)
    assert resp.status_code == 404


def test_list_tasks_with_task(client, provider, api_key, auth_headers, app):
    from app.models import ProviderTask
    from app.extensions import db

    task = ProviderTask(
        receipt_token='task-001',
        provider_guid=provider.guid,
        request_guid='sr-001',
        status='dispatched',
        patient_guid='pat-001',
        careplan_title='CGM Monitoring',
    )
    db.session.add(task)
    db.session.commit()

    resp = client.get('/api/v1/provider-tasks/my', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['receipt_token'] == 'task-001'
    assert data[0]['monitoring_interval_seconds'] is None
    assert data[0]['total_observations_submitted'] == 0
