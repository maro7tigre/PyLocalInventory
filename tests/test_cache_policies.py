"""Invariants shared by the RAM session cache and the disk cache.

The two cache layers must stay consistent: the RAM per-view cap and the
per-tab total must be strictly nested inside the disk per-section cap, and
the staleness constant must match the tab-switch refresh throttle.
"""

import unittest

import core.cache_policies as policies
from core.cache_manager import (
    DEFAULT_MAX_VIEWS_PER_IDENTITY,
    DEFAULT_MAX_ROWS_PER_SECTION,
    DEFAULT_MAX_STOCK_ROWS,
    DEFAULT_MAX_RECORD_AGE_SECONDS,
    DEFAULT_MAX_VIEW_AGE_SECONDS,
    DEFAULT_VACUUM_MIN_DB_BYTES,
)
from core.session_cache import DEFAULT_STALE_SECONDS, SessionCache


class CachePoliciesAlignmentTests(unittest.TestCase):
    def test_ram_per_view_cap_below_disk_section_cap(self):
        self.assertLessEqual(
            policies.RAM_MAX_RECORDS_PER_VIEW,
            policies.DISK_MAX_ROWS_PER_SECTION,
        )

    def test_ram_total_cap_below_disk_section_cap(self):
        self.assertLessEqual(
            policies.RAM_MAX_TOTAL_RECORDS_PER_TAB,
            policies.DISK_MAX_ROWS_PER_SECTION,
        )

    def test_ram_view_cap_below_disk_view_cap(self):
        self.assertLessEqual(
            policies.RAM_MAX_VIEWS_PER_TAB,
            policies.DISK_MAX_VIEWS_PER_IDENTITY,
        )

    def test_disk_defaults_track_policies(self):
        self.assertEqual(DEFAULT_MAX_ROWS_PER_SECTION, policies.DISK_MAX_ROWS_PER_SECTION)
        self.assertEqual(DEFAULT_MAX_VIEWS_PER_IDENTITY, policies.DISK_MAX_VIEWS_PER_IDENTITY)
        self.assertEqual(DEFAULT_MAX_STOCK_ROWS, policies.DISK_MAX_STOCK_ROWS)

    def test_hygiene_defaults_track_policies(self):
        self.assertEqual(DEFAULT_MAX_VIEW_AGE_SECONDS, policies.DISK_MAX_VIEW_AGE_SECONDS)
        self.assertEqual(DEFAULT_MAX_RECORD_AGE_SECONDS, policies.DISK_MAX_RECORD_AGE_SECONDS)
        self.assertEqual(DEFAULT_VACUUM_MIN_DB_BYTES, policies.DISK_VACUUM_MIN_DB_BYTES)

    def test_record_ttl_longer_than_view_ttl(self):
        self.assertLess(
            policies.DISK_MAX_VIEW_AGE_SECONDS,
            policies.DISK_MAX_RECORD_AGE_SECONDS,
        )

    def test_ram_defaults_track_policies(self):
        cache = SessionCache()
        stats = cache.stats()
        self.assertEqual(stats['max_entries'], policies.RAM_MAX_VIEWS_PER_TAB)
        self.assertEqual(stats['max_records_per_entry'], policies.RAM_MAX_RECORDS_PER_VIEW)
        self.assertEqual(stats['max_total_records'], policies.RAM_MAX_TOTAL_RECORDS_PER_TAB)

    def test_stale_seconds_matches_tab_throttle(self):
        self.assertEqual(DEFAULT_STALE_SECONDS, policies.DEFAULT_STALE_SECONDS)
        self.assertEqual(policies.DEFAULT_STALE_SECONDS, 30.0)

    def test_all_bounds_are_positive(self):
        for value in (
            policies.RAM_MAX_VIEWS_PER_TAB,
            policies.RAM_MAX_RECORDS_PER_VIEW,
            policies.RAM_MAX_TOTAL_RECORDS_PER_TAB,
            policies.DISK_MAX_ROWS_PER_SECTION,
            policies.DISK_MAX_VIEWS_PER_IDENTITY,
            policies.DISK_MAX_STOCK_ROWS,
            policies.DEFAULT_STALE_SECONDS,
        ):
            self.assertGreater(value, 0)


if __name__ == '__main__':
    unittest.main()
