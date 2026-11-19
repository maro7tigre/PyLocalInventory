"""Unit tests for the on-disk SQLite cache (core/cache_manager.py)."""

import os
import tempfile
import time
import unittest
from decimal import Decimal

from core.cache_manager import CacheManager, _safe_table_name


class CacheManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = os.path.join(self.temp_dir.name, 'cache.db')
        self._managers = []

    def tearDown(self):
        for manager in self._managers:
            manager.close()
        self._managers.clear()

    def make_manager(self, **kwargs):
        kwargs.setdefault('db_path', self.db_path)
        kwargs.setdefault('host', '192.168.1.10')
        kwargs.setdefault('port', '8765')
        kwargs.setdefault('username', 'alice')
        manager = CacheManager(**kwargs)
        self._managers.append(manager)
        return manager

    def _rec(self, i):
        return {'ID': i, 'name': f'Item {i}', 'notes': None}

    def test_store_and_get_records_roundtrip(self):
        cache = self.make_manager()
        records = [self._rec(1), self._rec(2), self._rec(3)]
        self.assertEqual(cache.store_records('Products', records), 3)
        self.assertEqual(cache.count_records('Products'), 3)
        result = cache.get_records('Products')
        self.assertEqual(sorted(result.keys()), [1, 2, 3])
        self.assertEqual(result[2]['name'], 'Item 2')
        self.assertIn('ID', result[1])
        self.assertIsNone(result[1]['notes'])

    def test_get_records_by_ids_subset(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1), self._rec(2), self._rec(3)])
        result = cache.get_records('Products', [3, 1])
        self.assertEqual(sorted(result.keys()), [1, 3])

    def test_overwrite_by_row_id(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1)])
        cache.store_records('Products', [{'ID': 1, 'name': 'Updated', 'notes': 'x'}])
        result = cache.get_records('Products', [1])
        self.assertEqual(result[1]['name'], 'Updated')
        self.assertEqual(cache.count_records('Products'), 1)

    def test_identity_isolation(self):
        alice = self.make_manager(username='alice')
        bob = self.make_manager(username='bob')
        alice.store_records('Products', [self._rec(1)])
        bob.store_records('Products', [self._rec(99)])
        self.assertTrue(alice.has_record('Products', 1))
        self.assertFalse(alice.has_record('Products', 99))
        self.assertTrue(bob.has_record('Products', 99))
        self.assertFalse(bob.has_record('Products', 1))

    def test_has_record_missing(self):
        cache = self.make_manager()
        cache.store_records('Sales', [self._rec(7)])
        self.assertTrue(cache.has_record('Sales', 7))
        self.assertFalse(cache.has_record('Sales', 8))

    def test_delete_records_removes_only_requested_rows(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1), self._rec(2), self._rec(3)])
        self.assertEqual(cache.delete_records('Products', [1, 3]), 2)
        self.assertFalse(cache.has_record('Products', 1))
        self.assertTrue(cache.has_record('Products', 2))
        self.assertFalse(cache.has_record('Products', 3))
        self.assertEqual(cache.delete_records('Products', []), 0)

    def test_decimal_values_become_strings_like_the_wire(self):
        cache = self.make_manager()
        record = {'ID': 5, 'total_ht': Decimal('82.00'), 'total_ttc': Decimal('98.40')}
        cache.store_records('Sales', [record])
        result = cache.get_records('Sales', [5])
        self.assertEqual(result[5]['total_ht'], '82.00')
        self.assertEqual(result[5]['total_ttc'], '98.40')

    def test_view_roundtrip(self):
        cache = self.make_manager()
        cache.store_records('Sales', [self._rec(1), self._rec(2), self._rec(3)])
        cache.store_view(
            'Sales', '', 'total_ttc|desc', [3, 2, 1],
            has_more=True, after_id=1, after_sort='100.00',
        )
        view = cache.get_view('Sales', '', 'total_ttc|desc')
        self.assertIsNotNone(view)
        record_ids, has_more, after_id, after_sort, stored_at = view
        self.assertEqual(record_ids, [3, 2, 1])
        self.assertTrue(has_more)
        self.assertEqual(after_id, 1)
        self.assertEqual(after_sort, '100.00')
        self.assertGreater(stored_at, 0)

    def test_view_missing_returns_none(self):
        cache = self.make_manager()
        cache.store_view('Sales', 'foo', 'default', [1])
        self.assertIsNone(cache.get_view('Sales', 'foo', 'other'))
        self.assertIsNone(cache.get_view('Sales', 'bar', 'default'))

    def test_stock_roundtrip(self):
        cache = self.make_manager()
        cache.store_stock({1: 12, 2: 0.5})
        self.assertEqual(cache.get_stock(), {1: 12.0, 2: 0.5})
        self.assertEqual(cache.get_stock([2]), {2: 0.5})

    def test_sync_state_roundtrip(self):
        cache = self.make_manager()
        self.assertIsNone(cache.get_sync_state('Products'))
        cache.set_sync_state('Products', 1234)
        self.assertEqual(cache.get_sync_state('Products'), 1234)

    def test_reopen_persists(self):
        cache = self.make_manager()
        cache.store_records('Clients', [self._rec(11), self._rec(12)])
        cache.store_view('Clients', 'jo', 'default', [12, 11], has_more=False)
        cache.store_stock({9: 3})
        cache.close()

        reopened = self.make_manager()
        self.assertEqual(sorted(reopened.get_records('Clients').keys()), [11, 12])
        view = reopened.get_view('Clients', 'jo', 'default')
        self.assertEqual(view[0], [12, 11])
        self.assertEqual(reopened.get_stock(), {9: 3.0})

    def test_row_cap_eviction_keeps_newest(self):
        cache = self.make_manager(max_rows_per_section=3)
        for i in range(1, 6):
            cache.store_records('Products', [self._rec(i)])
        self.assertEqual(cache.count_records('Products'), 3)
        result = cache.get_records('Products')
        self.assertEqual(sorted(result.keys()), [3, 4, 5])

    def test_view_cap_eviction(self):
        cache = self.make_manager(max_views_per_identity=2)
        for i in range(4):
            cache.store_view('Products', f'q{i}', 'default', [i])
        stats = cache.stats()
        self.assertLessEqual(stats['views'], 2)

    def test_drop_section_removes_rows_and_views(self):
        cache = self.make_manager()
        cache.store_records('Sales', [self._rec(1)])
        cache.store_view('Sales', '', 'default', [1])
        cache.store_records('Products', [self._rec(2)])
        self.assertTrue(cache.drop_section('Sales'))
        self.assertEqual(cache.count_records('Sales'), 0)
        self.assertIsNone(cache.get_view('Sales', '', 'default'))
        self.assertEqual(cache.count_records('Products'), 1)

    def test_clear_identity_only_this_identity(self):
        alice = self.make_manager(username='alice')
        bob = self.make_manager(username='bob')
        alice.store_records('Products', [self._rec(1)])
        bob.store_records('Products', [self._rec(2)])
        alice.store_view('Products', '', 'default', [1])
        alice.set_sync_state('Products', 5)
        self.assertTrue(alice.clear_identity())
        self.assertEqual(alice.count_records('Products'), 0)
        self.assertEqual(bob.count_records('Products'), 1)
        self.assertTrue(bob.has_record('Products', 2))

    def test_section_table_name_is_identifier_safe(self):
        self.assertEqual(_safe_table_name('Products'), 'cache_Products')
        self.assertEqual(_safe_table_name('Sales Items'), 'cache_Sales_Items')
        self.assertRegex(_safe_table_name('123'), r'^cache_[A-Za-z_]')

    def test_stats_reports_counts(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1), self._rec(2)])
        cache.store_view('Products', '', 'default', [1, 2])
        cache.store_stock({1: 5})
        stats = cache.stats()
        self.assertTrue(stats['opened'])
        self.assertEqual(stats['identity'], '192.168.1.10|8765|alice')
        section_rows = {s['section']: s['rows'] for s in stats['sections']}
        self.assertEqual(section_rows.get('cache_Products'), 2)
        self.assertEqual(stats['views'], 1)
        self.assertEqual(stats['stock_rows'], 1)

    def _age_rows(self, cache, view_age, record_age):
        now = time.time()
        with cache._lock:
            cache._conn.execute(
                "UPDATE views SET stored_at=? WHERE identity=?",
                (now - view_age, cache.identity),
            )
            cache._conn.execute(
                "UPDATE stock SET stored_at=? WHERE identity=?",
                (now - view_age, cache.identity),
            )
            cache._conn.execute(
                "UPDATE cache_Products SET stored_at=? WHERE identity=?",
                (now - record_age, cache.identity),
            )
            cache._conn.commit()

    def test_cleanup_expired_removes_old_rows_only(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1), self._rec(2)])
        cache.store_view('Products', 'q', 'default', [1, 2])
        cache.store_stock({1: 5})
        self._age_rows(cache, view_age=10 * 86400, record_age=40 * 86400)

        result = cache.hygiene(
            view_max_age=7 * 86400, record_max_age=30 * 86400, vacuum=False
        )
        self.assertEqual(result['removed'], 4)
        self.assertEqual(result['vacuum_freed_bytes'], 0)
        self.assertEqual(cache.all_record_ids('Products'), [])
        self.assertIsNone(cache.get_view('Products', 'q', 'default'))
        self.assertEqual(cache.get_stock(), {})

    def test_cleanup_expired_keeps_fresh_rows(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1)])
        cache.store_view('Products', 'q', 'default', [1])
        cache.store_stock({1: 5})
        result = cache.hygiene(vacuum=False)
        self.assertEqual(result['removed'], 0)
        self.assertEqual(cache.all_record_ids('Products'), [1])
        self.assertIsNotNone(cache.get_view('Products', 'q', 'default'))
        self.assertEqual(cache.get_stock(), {1: 5.0})

    def test_cleanup_respects_view_vs_record_ttl(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1)])
        cache.store_view('Products', 'q', 'default', [1])
        # Views older than their TTL, records still within theirs.
        self._age_rows(cache, view_age=10 * 86400, record_age=5 * 86400)
        result = cache.hygiene(
            view_max_age=7 * 86400, record_max_age=30 * 86400, vacuum=False
        )
        self.assertEqual(result['removed'], 1)
        self.assertIsNone(cache.get_view('Products', 'q', 'default'))
        self.assertEqual(cache.all_record_ids('Products'), [1])

    def test_vacuum_skips_small_db(self):
        cache = self.make_manager()
        self.assertEqual(cache.vacuum(), 0)

    def test_open_runs_launch_sweep(self):
        cache = self.make_manager()
        cache.store_records('Products', [self._rec(1)])
        cache.store_view('Products', 'q', 'default', [1])
        self._age_rows(cache, view_age=10 * 86400, record_age=40 * 86400)
        cache.close()

        reopened = self.make_manager()
        self.assertEqual(reopened.all_record_ids('Products'), [])
        self.assertIsNone(reopened.get_view('Products', 'q', 'default'))


if __name__ == '__main__':
    unittest.main()
