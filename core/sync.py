"""Background incremental sync for network clients.

``RemoteDatabase.sync_section`` pulls the host's change log for one section
and applies the delta to the local SQLite cache, so a client stays fresh
without re-downloading whole tables. ``SyncCoordinator`` drives that on a
timer and reports each pass's outcome through a Qt signal so the UI can show
sync freshness without coupling UI code to the sync mechanics.
"""

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_SECONDS = 30
MAX_BACKOFF_SECONDS = 600


class SyncCoordinator(QObject):
    """Periodically apply host changes into the client's on-disk cache.

    Emits ``status(state, applied, last_success, error)`` where state is
    'syncing', 'ok' or 'error', ``applied`` is the total number of change-log
    entries applied on the last pass, ``last_success`` is the wall-clock
    timestamp (seconds) of the last fully-successful pass (0 when never) and
    ``error`` is the first error message encountered ('' when none).
    """

    status = Signal(str, int, float, str)

    def __init__(self, database, sections, interval=DEFAULT_SYNC_INTERVAL_SECONDS, parent=None):
        super().__init__(parent)
        self.database = database
        self.sections = list(sections)
        self.interval = interval
        self.syncing = False
        self.last_success = 0.0
        self.last_applied_sections = set()
        self._pass_count = 0
        self._fail_streak = 0
        self._base_interval_ms = int(interval * 1000)

        self._timer = QTimer(self)
        self._timer.setInterval(self._base_interval_ms)
        self._timer.timeout.connect(self.sync_all)

    def start(self):
        """Run one pass immediately, then every ``interval`` seconds."""
        self._timer.setInterval(self._base_interval_ms)
        self.sync_all()
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def sync_all(self):
        """Apply all readable sections' pending changes in one pass.

        Runs synchronously; one short-timeout network call per section. Never
        raises - any per-section failure is reported through the status signal
        instead. When every section fails the host is considered unreachable:
        the client's ``offline`` flag is set (so tabs stop hanging on network
        refreshes) and the poll interval backs off exponentially up to
        ``MAX_BACKOFF_SECONDS``, resetting after the first successful pass.
        """
        if self.syncing or self.database is None:
            return
        self.syncing = True
        applied_sections = set()
        total_applied = 0
        failures = 0
        last_error = ''
        try:
            self.status.emit('syncing', 0, self.last_success, '')
            for section in self.sections:
                try:
                    result = self.database.sync_section(section)
                    if result and result.get('applied'):
                        total_applied += int(result['applied'])
                        applied_sections.add(section)
                except Exception as error:
                    failures += 1
                    last_error = last_error or str(error)
                    logger.exception("Incremental sync failed section=%s", section)
            self.last_applied_sections = applied_sections
            if failures == 0:
                self._on_success(total_applied)
            else:
                self._on_failure(failures, total_applied, last_error)
        finally:
            self.syncing = False

    def _on_success(self, total_applied):
        """Reset the failure streak/backoff, mark the host reachable and emit
        the success status."""
        self._fail_streak = 0
        if self._timer.interval() != self._base_interval_ms:
            self._timer.setInterval(self._base_interval_ms)
        self._set_offline(False)
        self.last_success = time.time()
        self._run_periodic_hygiene()
        self.status.emit('ok', total_applied, self.last_success, '')

    def _on_failure(self, failures, total_applied, last_error):
        """Back off and mark the host unreachable only when every section
        failed; a partial pass means the host is up and keeps normal pacing."""
        if failures >= len(self.sections):
            self._fail_streak += 1
            backoff = min(
                int(self.interval * (2 ** self._fail_streak)),
                MAX_BACKOFF_SECONDS,
            )
            if self._timer.interval() != backoff * 1000:
                self._timer.setInterval(backoff * 1000)
            self._set_offline(True)
            logger.warning(
                "Incremental sync fully failed streak=%d backoff=%ds",
                self._fail_streak, backoff,
            )
        self.status.emit('error', total_applied, self.last_success, last_error)

    def _set_offline(self, offline):
        """Mirror the connectivity state onto the client so tabs can skip
        network refreshes that would hang on a dead host."""
        try:
            self.database.offline = bool(offline)
        except Exception:
            logger.exception("Could not set offline flag on client")

    def _run_periodic_hygiene(self):
        """Sweep expired cached rows once every 10 successful passes, so the
        on-disk cache stays tidy between application launches."""
        self._pass_count += 1
        if self._pass_count % 10 != 0:
            return
        cache = getattr(self.database, 'cache', None)
        if cache is None or not hasattr(cache, 'hygiene'):
            return
        try:
            cache.hygiene()
        except Exception:
            logger.exception("Cache hygiene pass failed")
