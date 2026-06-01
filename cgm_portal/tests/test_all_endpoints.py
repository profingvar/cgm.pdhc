"""Smoke tests for all API endpoints."""
import json


def test_health_check(client):
    resp = client.get('/api/v1/health')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'


def test_list_tasks_empty(client, api_key, auth_headers):
    resp = client.get('/api/v1/provider-tasks/my', headers=auth_headers)
    assert resp.status_code == 200


def test_audit_log_empty(client, api_key, auth_headers):
    resp = client.get('/api/v1/audit-log', headers=auth_headers)
    assert resp.status_code == 200


def test_receipts_empty(client, api_key, auth_headers):
    resp = client.get('/api/v1/provider-receipts', headers=auth_headers)
    assert resp.status_code == 200


def test_push_without_secret(client):
    resp = client.post('/api/v1/inbound/push',
                       json={'resourceType': 'Bundle'})
    # PUSH_SECRET is set in test config, so missing header = 401
    assert resp.status_code == 401


def test_receipt_ingest_without_key(client):
    resp = client.post('/api/v1/receipts/ingest',
                       json={'receipt_guid': 'r1', 'service_request_guid': 'sr1'})
    assert resp.status_code == 401


def test_receipt_ingest_valid(client, app):
    resp = client.post('/api/v1/receipts/ingest',
                       headers={'X-Service-Key': 'test-gateway-key',
                                'Content-Type': 'application/json'},
                       json={
                           'receipt_guid': 'r-001',
                           'service_request_guid': 'sr-001',
                           'patient_guid': 'pat-001',
                           'observations_stored': 5,
                           'accepted_at': '2026-04-01T12:00:00Z',
                       })
    assert resp.status_code == 202
    data = resp.get_json()
    assert data['action'] == 'created'


def test_create_api_key(client, api_key, auth_headers):
    resp = client.post('/api/v1/api-keys',
                       headers=auth_headers,
                       json={'scopes': 'read', 'label': 'test-key'})
    assert resp.status_code == 201
    data = resp.get_json()
    assert 'key' in data
    assert data['scopes'] == 'read'
