"""Background sync thread for development use."""
import logging
import threading
import time

logger = logging.getLogger(__name__)


class SyncScheduler:

    def __init__(self, app, subscription_service):
        self.app = app
        self.subscription_service = subscription_service
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        if not self.app.config.get('SYNC_ENABLED'):
            logger.info('Sync disabled, background thread not started')
            return

        interval = self.app.config.get('SYNC_INTERVAL_SECONDS', 60)
        logger.info('Starting background sync every %d seconds', interval)

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval,),
            daemon=True,
            name='sync-scheduler',
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self, interval):
        self._stop_event.wait(5)

        while not self._stop_event.is_set():
            try:
                with self.app.app_context():
                    new, updated, skipped = self.subscription_service.sync()
                    logger.info('Background sync: %d new, %d updated, %d skipped',
                                new, updated, skipped)
            except Exception as e:
                logger.error('Background sync error: %s', str(e))

            self._stop_event.wait(interval)
