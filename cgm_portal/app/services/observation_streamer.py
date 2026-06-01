"""ObservationStreamer — background thread that streams glucose observations.

Once a task is acknowledged, a streamer thread is spawned. It submits one
glucose observation per minute to the gateway (via ObservationSubmissionService)
until the task is manually stopped via POST /observe/complete.
"""
import logging
import threading
from datetime import datetime, timezone

from .glucose_simulator import GlucoseSimulator

logger = logging.getLogger(__name__)

# Registry of active streamers keyed by receipt_token
_active_streamers = {}
_lock = threading.Lock()


class ObservationStreamer:

    def __init__(self, app, receipt_token, provider_guid, transaction_guid,
                 interval_seconds=60):
        self.app = app
        self.receipt_token = receipt_token
        self.provider_guid = provider_guid
        self.transaction_guid = transaction_guid
        self.interval_seconds = interval_seconds
        self.simulator = GlucoseSimulator()
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f'cgm-stream-{self.receipt_token[:12]}',
        )
        self._thread.start()
        logger.info('Started glucose stream for task %s (every %ds)',
                    self.receipt_token, self.interval_seconds)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info('Stopped glucose stream for task %s', self.receipt_token)

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self):
        # Small delay to let the acknowledge transaction commit
        self._stop_event.wait(2)

        while not self._stop_event.is_set():
            try:
                self._submit_one_reading()
            except Exception as e:
                logger.error('Stream error for %s: %s', self.receipt_token, e)

            self._stop_event.wait(self.interval_seconds)

    def _submit_one_reading(self):
        from .observation_submission import ObservationSubmissionService

        value = self.simulator.next_value()
        now = datetime.now(timezone.utc).isoformat()

        observations = [{
            'transaction_guid': self.transaction_guid,
            'value': value,
            'recorded_at': now,
        }]

        with self.app.app_context():
            task, log_entry = ObservationSubmissionService.submit_batch(
                receipt_token=self.receipt_token,
                provider_guid=self.provider_guid,
                observations=observations,
            )
            logger.info('Streamed glucose %.1f mmol/L for %s (batch #%d, gw=%s)',
                        value, self.receipt_token, log_entry.batch_number,
                        log_entry.gateway_status)


def start_stream(app, receipt_token, provider_guid, transaction_guid='tx-glucose',
                 interval_seconds=60):
    """Start a background glucose stream for a task. Idempotent."""
    with _lock:
        existing = _active_streamers.get(receipt_token)
        if existing and existing.is_running:
            return existing  # already streaming

        streamer = ObservationStreamer(
            app=app,
            receipt_token=receipt_token,
            provider_guid=provider_guid,
            transaction_guid=transaction_guid,
            interval_seconds=interval_seconds,
        )
        _active_streamers[receipt_token] = streamer
        streamer.start()
        return streamer


def stop_stream(receipt_token):
    """Stop a running glucose stream. Idempotent."""
    with _lock:
        streamer = _active_streamers.pop(receipt_token, None)
        if streamer:
            streamer.stop()
        return streamer


def get_stream_status(receipt_token):
    """Check if a stream is running for a task."""
    with _lock:
        streamer = _active_streamers.get(receipt_token)
        if streamer and streamer.is_running:
            return {'streaming': True, 'interval_seconds': streamer.interval_seconds}
        return {'streaming': False}


def list_active_streams():
    """List all active stream receipt_tokens."""
    with _lock:
        return [rt for rt, s in _active_streamers.items() if s.is_running]
