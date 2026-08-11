"""Tests for the Supplier Account feature.

Mirrors test_client_account.py: the supplier side of the account API -
per-Import history, payments (add/edit/delete) and the LAN permission gate.
Real PostgreSQL is not required - queries are exercised against scripted
cursors using the real core.database.Database methods.
"""

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.database import (
    Database,
    SUPPLIER_ACCOUNT_IMPORT_FIELDS,
    SUPPLIER_ACCOUNT_IMPORT_SUMMARY_FIELDS,
    SUPPLIER_ACCOUNT_PAYMENT_FIELDS,
    normalize_supplier_account,
)
from core.network.server import _check_permission


class _FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeCursor:
    """Scripted cursor for the real Database supplier-account queries."""

    def __init__(self):
        self.queries = []
        self._sql = None
        self.rowcount = 0
        self.supplier_row = (5, "Fournisseur Alpha")
        self.missing_supplier = False
        self.import_rows = [
            (1, "2026-07-01", 10, "Porte", Decimal("2"), Decimal("100"),
             Decimal("20"), "", False, "host"),
            (2, "2026-07-05", 11, "Poignée", Decimal("3"), Decimal("50"),
             Decimal("20"), "", False, "host"),
        ]
        self.summary_rows = [
            (1, "2026-07-01", "BL-2026-1", False, Decimal("20"),
             Decimal("240.00")),
        ]
        self.payment_rows = [
            (7, 2, None, "2026-07-06", Decimal("100.00")),
        ]
        self.block_row = (2, "2026-07-05", Decimal("20"), "", False,
                          "BL-2026-2", "Fournisseur Alpha", "Fournisseur Alpha")
        self.payment_return = (77,)

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self._sql = sql

    def fetchone(self):
        sql = self._sql
        if "SELECT id, username FROM suppliers" in sql:
            return None if self.missing_supplier else self.supplier_row
        if "SELECT username FROM suppliers" in sql:
            return None if self.missing_supplier else (self.supplier_row[1],)
        if "FROM imports i WHERE i.id" in sql:
            return self.block_row
        if "SELECT 1" in sql:
            return (1,)
        if "INSERT INTO payments" in sql:
            return (self.payment_return[0],)
        if "UPDATE payments" in sql or "DELETE FROM payments" in sql:
            return self.payment_return
        return None

    def fetchall(self):
        sql = self._sql
        if "FROM imports i JOIN import_items ii" in sql:
            return self.import_rows
        if "FROM imports i LEFT JOIN import_items ii" in sql:
            return self.summary_rows
        if "FROM payments" in sql:
            return self.payment_rows
        return []


class SupplierAccountSchemaTests(unittest.TestCase):
    def test_import_fields_are_exactly_the_10_column_join(self):
        self.assertEqual(
            SUPPLIER_ACCOUNT_IMPORT_FIELDS,
            (
                "import_id", "date", "item_id", "product", "quantity",
                "unit_price", "vat", "notes", "is_historical",
                "created_by_username",
            ),
        )
        self.assertEqual(len(SUPPLIER_ACCOUNT_IMPORT_FIELDS), 10)

    def test_payment_fields_are_the_5_column_payments_select(self):
        self.assertEqual(
            SUPPLIER_ACCOUNT_PAYMENT_FIELDS,
            ("payment_id", "import_id", "item_id", "date", "amount"),
        )

    def test_import_summary_fields_are_the_7_column_per_import_contract(self):
        self.assertEqual(
            SUPPLIER_ACCOUNT_IMPORT_SUMMARY_FIELDS,
            (
                "import_id", "date", "bl_number", "is_historical", "total",
                "paid", "remaining",
            ),
        )

    def test_normalize_supplier_account_builds_named_dicts(self):
        import_rows = [
            (1, "01-08-2026", 10, "Porte", Decimal("2"), Decimal("100"),
             Decimal("20"), "", False, "host"),
        ]
        payment_rows = [
            (7, 1, None, "02-08-2026", Decimal("100.00")),
        ]
        account = normalize_supplier_account(import_rows, payment_rows)
        self.assertEqual(len(account["imports"]), 1)
        self.assertEqual(len(account["payments"]), 1)
        imp = account["imports"][0]
        self.assertEqual(imp["import_id"], 1)
        self.assertEqual(imp["product"], "Porte")
        self.assertIn("created_by_username", imp)
        self.assertEqual(account["payments"][0]["payment_id"], 7)
        self.assertEqual(account["payments"][0]["amount"], Decimal("100.00"))


class SupplierAccountBackendTests(unittest.TestCase):
    def setUp(self):
        self.cursor = _FakeCursor()
        self.db = Database.__new__(Database)
        self.db.cursor = self.cursor
        self.db.conn = _FakeConn()

    def test_get_supplier_account_returns_named_import_and_payment_rows(self):
        account = self.db.get_supplier_account(5)
        self.assertEqual(len(account["imports"]), 2)
        self.assertEqual(len(account["payments"]), 1)
        self.assertEqual(account["imports"][0]["import_id"], 1)
        self.assertEqual(account["imports"][0]["product"], "Porte")
        self.assertEqual(account["payments"][0]["payment_id"], 7)
        # Only supplier rows are fetched: no created_by ownership filter.
        ownership = [p for _, p in self.cursor.queries if "created_by" in str(p)]
        self.assertFalse(ownership)

    def test_get_supplier_account_missing_supplier_raises(self):
        self.cursor.missing_supplier = True
        with self.assertRaises(ValueError):
            self.db.get_supplier_account(99)
        self.assertEqual(self.db.conn.rollbacks, 0)

    def test_get_supplier_import_summaries_computes_total_paid_remaining(self):
        result = self.db.get_supplier_import_summaries(5)
        self.assertEqual(len(result["imports"]), 1)
        summary = result["imports"][0]
        self.assertEqual(summary["import_id"], 1)
        self.assertEqual(summary["bl_number"], "BL-2026-1")
        # raw 240.00 at 20% VAT => 288.00 TTC; no payments on import 1.
        self.assertEqual(summary["total"], Decimal("288.00"))
        self.assertEqual(summary["paid"], Decimal("0"))
        self.assertEqual(summary["remaining"], Decimal("288.00"))

    def test_get_supplier_import_items_returns_block_and_payments(self):
        result = self.db.get_supplier_import_items(2)
        self.assertEqual(len(result["imports"]), 2)
        self.assertEqual(len(result["payments"]), 1)
        block = result["import"]
        self.assertEqual(block["import_id"], 2)
        self.assertEqual(block["bl_number"], "BL-2026-2")
        self.assertEqual(block["supplier_name"], "Fournisseur Alpha")

    def test_add_supplier_payment_verifies_ownership_and_inserts(self):
        payment_id = self.db.add_supplier_payment(5, 2, None, "150.00", "2026-07-07")
        self.assertEqual(payment_id, 77)
        insert_sql, insert_params = self.cursor.queries[-1]
        self.assertIn("INSERT INTO payments", insert_sql)
        self.assertIn("import_id", insert_sql)
        self.assertEqual(insert_params, (2, None, 150.0, "2026-07-07"))
        self.assertEqual(self.db.conn.commits, 1)

    def test_add_supplier_payment_rejects_non_positive_amount(self):
        with self.assertRaises(ValueError):
            self.db.add_supplier_payment(5, 2, None, "0", "2026-07-07")

    def test_update_supplier_payment_touches_only_import_payments(self):
        self.cursor.payment_return = (77,)
        result = self.db.update_supplier_payment(77, "200.00")
        self.assertEqual(result, 77)
        update_sql, update_params = self.cursor.queries[-1]
        self.assertIn("UPDATE payments SET amount", update_sql)
        self.assertIn("import_id IS NOT NULL", update_sql)
        self.assertEqual(update_params, (200.0, 77))

    def test_delete_supplier_payment_deletes_only_by_payment_id(self):
        self.cursor.payment_return = (12,)
        result = self.db.delete_supplier_payment(12)
        self.assertEqual(result, 12)
        delete_sql, delete_params = self.cursor.queries[-1]
        self.assertIn("DELETE FROM payments", delete_sql)
        self.assertIn("import_id IS NOT NULL", delete_sql)
        self.assertEqual(delete_params, (12,))

    def test_delete_supplier_payment_missing_rolls_back_and_raises(self):
        self.cursor.payment_return = None
        with patch.object(self.db.conn, "rollback") as rollback:
            with self.assertRaises(ValueError):
                self.db.delete_supplier_payment(99)
        rollback.assert_called_once()


class SupplierAccountServerPermissionTests(unittest.TestCase):
    def _user(self, suppliers_read=False, imports_write=False):
        return {
            "is_superadmin": False,
            "permissions": {
                "Suppliers": {
                    "read": suppliers_read, "write": False, "delete": False,
                },
                "Imports": {
                    "read": True, "write": imports_write, "delete": False,
                },
            },
        }

    def test_account_read_denied_without_suppliers_read(self):
        allowed, _ = _check_permission(
            self._user(), "get_supplier_account", [5], {}
        )
        self.assertFalse(allowed)

    def test_account_read_allowed_with_suppliers_read(self):
        allowed, _ = _check_permission(
            self._user(suppliers_read=True), "get_supplier_import_summaries", [5], {}
        )
        self.assertTrue(allowed)

    def test_payment_write_denied_without_imports_write(self):
        allowed, _ = _check_permission(
            self._user(suppliers_read=True), "add_supplier_payment", [5, 2, None, 10, "2026-07-07"], {}
        )
        self.assertFalse(allowed)

    def test_payment_write_allowed_with_suppliers_read_and_imports_write(self):
        allowed, _ = _check_permission(
            self._user(suppliers_read=True, imports_write=True),
            "update_supplier_payment", [77, 10], {},
        )
        self.assertTrue(allowed)

    def test_superadmin_allowed(self):
        allowed, _ = _check_permission(
            {"is_superadmin": True, "permissions": {}},
            "delete_supplier_payment", [77], {},
        )
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main()
