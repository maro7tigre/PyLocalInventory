"""Phase 9 tests: background incremental sync coordinator.

Verifies that SyncCoordinator runs one sync pass per section, aggregates
applied change counts and per-section results, reports success/failure through
its status signal, never raises on per-section errors, and skips runs while a
previous pass is still in flight.
"""

import time
import unittest

from PySide6.QtCore import QCoreApplication

from core.sync import SyncCoordinator


class _FakeDatabase:
    """Records sync_section calls and returns a scripted result per section."""

    def __init__(self, results=None, errors=None, sleep=0.0):
        self.results = results or {}
        self.errors = errors or set()
        self.sleep = sleep
        self.calls = []

    def sync_section(self, section):
        self.calls.append(section)
        if self.sleep:
            time.sleep(self.sleep)
        if section in self.errors:
            raise RuntimeError(f"boom:{section}")
        return self.results.get(section, {'applied': 0, 'last_seq': 0, 'has_more': False})


class _StatusSink:
    def __init__(self):
        self.states = []

    def __call__(self, state, applied, last_success, error):
        self.states.append((state, applied, error))


class SyncCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make(self, database, sections=None):
        coordinator = SyncCoordinator(
            database, sections if sections is not None else ['Products', 'Clients']
        )
        sink = _StatusSink()
        coordinator.status.connect(sink)
        return coordinator, sink

    def test_sync_all_calls_each_section_once(self):
        database = _FakeDatabase({
            'Products': {'applied': 2, 'last_seq': 5, 'has_more': False},
            'Clients': {'applied': 1, 'last_seq': 3, 'has_more': False},
        })
        coordinator, sink = self.make(database)
        coordinator.sync_all()
        self.assertEqual(database.calls, ['Products', 'Clients'])
        self.assertEqual(coordinator.last_success > 0, True)
        self.assertEqual(coordinator.last_applied_sections, {'Products', 'Clients'})
        self.assertEqual(sink.states[0][0], 'syncing')
        self.assertEqual(sink.states[-1][0], 'ok')
        self.assertEqual(sink.states[-1][1], 3)

    def test_empty_results_are_ok_with_zero_applied(self):
        database = _FakeDatabase({})
        coordinator, sink = self.make(database)
        coordinator.sync_all()
        self.assertEqual(sink.states[-1], ('ok', 0, ''))
        self.assertEqual(coordinator.last_applied_sections, set())

    def test_section_error_reports_error_but_continues(self):
        database = _FakeDatabase(
            {'Products': {'applied': 4, 'last_seq': 9, 'has_more': False}},
            errors={'Clients'},
        )
        coordinator, sink = self.make(database)
        coordinator.sync_all()
        self.assertEqual(database.calls, ['Products', 'Clients'])
        self.assertEqual(sink.states[-1][0], 'error')
        self.assertIn('boom', sink.states[-1][2])
        self.assertEqual(coordinator.last_success, 0.0)
        self.assertEqual(coordinator.last_applied_sections, {'Products'})

    def test_skip_run_while_previous_still_in_flight(self):
        database = _FakeDatabase(
            {'Products': {'applied': 1, 'last_seq': 1, 'has_more': False}},
            sleep=0.05,
        )
        coordinator, sink = self.make(database, sections=['Products'])
        coordinator.syncing = True
        coordinator.sync_all()
        self.assertEqual(database.calls, [])
        self.assertEqual(sink.states, [])

    def test_none_database_is_noop(self):
        coordinator, sink = self.make(None)
        coordinator.sync_all()
        self.assertEqual(sink.states, [])
        self.assertEqual(coordinator.last_success, 0.0)

    def test_full_failure_marks_offline_and_backs_off(self):
        database = _FakeDatabase({}, errors={'Products', 'Clients'})
        coordinator, _ = self.make(database)
        coordinator.sync_all()
        self.assertTrue(database.offline)
        self.assertEqual(coordinator._fail_streak, 1)
        self.assertEqual(coordinator._timer.interval(), 60_000)

    def test_recovery_resets_backoff_and_offline(self):
        database = _FakeDatabase({}, errors={'Products', 'Clients'})
        coordinator, _ = self.make(database)
        coordinator.sync_all()
        self.assertTrue(database.offline)
        database.errors = set()
        coordinator.sync_all()
        self.assertFalse(database.offline)
        self.assertEqual(coordinator._fail_streak, 0)
        self.assertEqual(coordinator._timer.interval(), 30_000)

    def test_partial_failure_keeps_online_and_pacing(self):
        database = _FakeDatabase(
            {'Products': {'applied': 1, 'last_seq': 1, 'has_more': False}},
            errors={'Clients'},
        )
        coordinator, sink = self.make(database)
        coordinator.sync_all()
        self.assertFalse(getattr(database, 'offline', False))
        self.assertEqual(coordinator._fail_streak, 0)
        self.assertEqual(coordinator._timer.interval(), 30_000)
        self.assertEqual(sink.states[-1][0], 'error')

    def test_periodic_hygiene_runs_every_10_passes(self):
        database = _FakeDatabase({})
        cache = _HygieneSpy()
        database.cache = cache
        coordinator, _ = self.make(database)
        for _ in range(9):
            coordinator.sync_all()
        self.assertEqual(cache.hygiene_calls, 0)
        coordinator.sync_all()
        self.assertEqual(cache.hygiene_calls, 1)

    def test_hygiene_failure_is_not_fatal(self):
        database = _FakeDatabase({})

        class _BrokenCache:
            def hygiene(self):
                raise RuntimeError("db locked")

        database.cache = _BrokenCache()
        coordinator, sink = self.make(database)
        coordinator._pass_count = 9
        coordinator.sync_all()
        self.assertEqual(sink.states[-1][0], 'ok')


class _HygieneSpy:
    def __init__(self):
        self.hygiene_calls = 0

    def hygiene(self):
        self.hygiene_calls += 1


if __name__ == '__main__':
    unittest.main()
