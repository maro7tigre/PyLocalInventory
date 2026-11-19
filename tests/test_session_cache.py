"""Unit tests for the bounded session RAM cache (core/session_cache.py)."""

import time
import unittest

from core.session_cache import DEFAULT_STALE_SECONDS, SessionCache


def _rec(i):
    return {'ID': i, 'name': f'Item {i}'}


class SessionCacheTests(unittest.TestCase):
    def test_set_and_get_roundtrip(self):
        cache = SessionCache()
        cache.set_first_batch(
            'k', [_rec(1), _rec(2)], has_more=True, after_id=2, after_sort='B'
        )
        entry = cache.get('k')
        self.assertIsNotNone(entry)
        self.assertEqual(len(entry.records), 2)
        self.assertTrue(entry.has_more)
        self.assertEqual(entry.after_id, 2)
        self.assertEqual(entry.after_sort, 'B')
        self.assertEqual(entry.batches, 1)

    def test_miss_returns_none(self):
        cache = SessionCache()
        self.assertIsNone(cache.get('missing'))
        self.assertNotIn('missing', cache)

    def test_append_extends_and_advances_cursor(self):
        cache = SessionCache()
        cache.set_first_batch(
            'k', [_rec(1), _rec(2)], has_more=True, after_id=2, after_sort='B'
        )
        entry = cache.append_batch(
            'k', [_rec(3)], has_more=False, after_id=3, after_sort='C'
        )
        self.assertEqual([r['ID'] for r in entry.records], [1, 2, 3])
        self.assertFalse(entry.has_more)
        self.assertEqual(entry.after_id, 3)
        self.assertEqual(entry.batches, 2)

    def test_append_missing_key_creates_fresh_entry(self):
        cache = SessionCache()
        entry = cache.append_batch('new', [_rec(9)])
        self.assertEqual([r['ID'] for r in entry.records], [9])
        self.assertEqual(len(cache), 1)

    def test_invalidate_one_key(self):
        cache = SessionCache()
        cache.set_first_batch('a', [_rec(1)])
        cache.set_first_batch('b', [_rec(2)])
        cache.invalidate('a')
        self.assertIsNone(cache.get('a'))
        self.assertIsNotNone(cache.get('b'))

    def test_invalidate_all(self):
        cache = SessionCache()
        cache.set_first_batch('a', [_rec(1)])
        cache.set_first_batch('b', [_rec(2)])
        cache.invalidate()
        self.assertEqual(len(cache), 0)

    def test_clear(self):
        cache = SessionCache()
        cache.set_first_batch('a', [_rec(1)])
        cache.set_first_batch('b', [_rec(2)])
        cache.clear()
        self.assertEqual(len(cache), 0)
        self.assertEqual(cache.stats()['records'], 0)

    def test_lru_eviction(self):
        cache = SessionCache(max_entries=2)
        cache.set_first_batch('a', [_rec(1)])
        cache.set_first_batch('b', [_rec(2)])
        cache.get('a')  # touch a so b becomes the least-recently used
        cache.set_first_batch('c', [_rec(3)])
        self.assertIsNotNone(cache.get('a'))
        self.assertIsNone(cache.get('b'))
        self.assertIsNotNone(cache.get('c'))

    def test_records_per_entry_cap(self):
        cache = SessionCache(max_records_per_entry=3)
        cache.set_first_batch('k', [_rec(1), _rec(2), _rec(3), _rec(4)])
        self.assertEqual(len(cache.get('k').records), 3)

    def test_total_record_budget(self):
        cache = SessionCache(max_records_per_entry=100, max_total_records=5, max_entries=10)
        cache.set_first_batch('a', [_rec(i) for i in range(4)])
        cache.set_first_batch('b', [_rec(i) for i in range(4)])
        self.assertEqual(len(cache), 1)
        self.assertIsNotNone(cache.get('b'))
        self.assertIsNone(cache.get('a'))

    def test_is_stale(self):
        cache = SessionCache()
        cache.set_first_batch('k', [_rec(1)])
        entry = cache.get('k')
        self.assertFalse(entry.is_stale())
        entry.last_fetched = time.monotonic() - DEFAULT_STALE_SECONDS - 1
        self.assertTrue(entry.is_stale())

    def test_stats_track_hits_and_misses(self):
        cache = SessionCache()
        cache.set_first_batch('k', [_rec(1)])
        cache.get('k')
        cache.get('zz')
        stats = cache.stats()
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
        self.assertEqual(stats['entries'], 1)
        self.assertEqual(stats['records'], 1)

    def test_thread_safety_smoke(self):
        cache = SessionCache(max_entries=4)
        errors = []

        def writer():
            try:
                for i in range(50):
                    cache.set_first_batch(i % 4, [_rec(i)])
                    cache.get((i + 1) % 4)
                    cache.append_batch(i % 4, [_rec(i)])
            except Exception as exc:  # pragma: no cover - failure reporting
                errors.append(exc)

        import threading
        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertLessEqual(len(cache), 4)


if __name__ == '__main__':
    unittest.main()
