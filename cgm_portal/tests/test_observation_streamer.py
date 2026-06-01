"""Tests for the observation streamer (background auto-stream)."""
import time
from unittest.mock import patch, MagicMock
from app.services.observation_streamer import (
    ObservationStreamer, start_stream, stop_stream, get_stream_status,
    list_active_streams, _active_streamers, _lock,
)


def _cleanup():
    """Clear the global streamer registry between tests."""
    with _lock:
        for rt, s in list(_active_streamers.items()):
            s.stop()
        _active_streamers.clear()


def test_streamer_lifecycle(app, provider):
    """Streamer starts, runs, and stops cleanly."""
    _cleanup()
    with app.app_context():
        from app.extensions import db
        from app.models import ProviderTask, InboundRequest

        task = ProviderTask(
            receipt_token='stream-test-001',
            provider_guid=provider.guid,
            request_guid='sr-stream-001',
            status='acknowledged',
            patient_guid='pat-001',
        )
        db.session.add(task)
        inbound = InboundRequest(
            request_guid='sr-stream-001',
            provider_guid=provider.guid,
            receipt_token='stream-test-001',
            careplan_json={},
            patient_guid='pat-001',
            grant_token='grant-test',
            status='new',
            checksum='abc',
        )
        db.session.add(inbound)
        db.session.commit()

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        streamer = start_stream(
            app=app,
            receipt_token='stream-test-001',
            provider_guid=provider.guid,
            transaction_guid='tx-glucose',
            interval_seconds=1,  # fast for testing
        )

        assert streamer.is_running
        assert get_stream_status('stream-test-001')['streaming'] is True
        assert 'stream-test-001' in list_active_streams()

        # Let it run for a couple ticks
        time.sleep(4)

        stop_stream('stream-test-001')
        assert not streamer.is_running
        assert get_stream_status('stream-test-001')['streaming'] is False

    # Verify observations were logged
    with app.app_context():
        from app.models import ObservationLog
        logs = ObservationLog.query.filter_by(receipt_token='stream-test-001').all()
        assert len(logs) >= 1  # at least one batch was submitted

    _cleanup()


def test_start_idempotent(app, provider):
    """Starting a stream twice returns the same streamer."""
    _cleanup()
    with app.app_context():
        from app.extensions import db
        from app.models import ProviderTask, InboundRequest

        task = ProviderTask(
            receipt_token='stream-idem-001',
            provider_guid=provider.guid,
            request_guid='sr-idem-001',
            status='acknowledged',
            patient_guid='pat-001',
        )
        db.session.add(task)
        inbound = InboundRequest(
            request_guid='sr-idem-001',
            provider_guid=provider.guid,
            receipt_token='stream-idem-001',
            careplan_json={},
            patient_guid='pat-001',
            grant_token='grant-test',
            status='new',
            checksum='abc',
        )
        db.session.add(inbound)
        db.session.commit()

    with patch('app.services.status_callback.StatusCallbackService.push_status'):
        s1 = start_stream(app=app, receipt_token='stream-idem-001',
                          provider_guid=provider.guid, interval_seconds=60)
        s2 = start_stream(app=app, receipt_token='stream-idem-001',
                          provider_guid=provider.guid, interval_seconds=60)
        assert s1 is s2

    _cleanup()


def test_stop_nonexistent():
    """Stopping a stream that doesn't exist is a no-op."""
    _cleanup()
    result = stop_stream('nonexistent')
    assert result is None


def test_stream_status_endpoint(client, provider, api_key, auth_headers, app):
    """GET /observe/status returns stream info."""
    from app.extensions import db
    from app.models import ProviderTask

    task = ProviderTask(
        receipt_token='stream-status-001',
        provider_guid=provider.guid,
        request_guid='sr-status-001',
        status='monitoring',
        patient_guid='pat-001',
    )
    db.session.add(task)
    db.session.commit()

    resp = client.get('/api/v1/provider-tasks/stream-status-001/observe/status',
                      headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'streaming' in data
    assert data['task_status'] == 'monitoring'
