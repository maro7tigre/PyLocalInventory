"""Focused no-database regression tests for the Factures presentation contract."""

import json
import os
import time
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.moroccan_dirham_words import amount_to_words
from core.database import Database
from core.calculations import to_decimal
from core.network.client import RemoteDatabase
from core.network.server import _check_permission
from core.profiles import ProfileClass
from core.sales_states import is_financially_active
from ui.facture_document import _document_data, render_facture_preview_pages
from ui.tabs.factures_tab import DevisSelectorDialog, FactureEditor, FacturePreviewDialog, FacturesTab


def _wait_until(predicate, timeout=2.0):
    """Bounded event-loop pump for the editor's async catalog/refresh loads."""
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class _FactureDatabase:
    def __init__(self, clients=None):
        self.saved = None
        self.clients = clients if clients is not None else [
            {"id": 7, "name": "Client Test", "username": "client.test"}
        ]

    def get_sale_catalog(self, *_args, **_kwargs):
        return {"clients": self.clients}

    def save_facture_with_items(self, header, items, facture_id=None):
        self.saved = (header, items, facture_id)
        return {"facture_id": 11, "facture_number": "FA001/2026"}

    def has_permission(self, _section, _action):
        return True

    def list_factures(self):
        return []


class _Cursor:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def fetchall(self):
        return []


class _CatalogCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""

    def execute(self, sql, _params=None):
        self.sql = sql

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.committed = False
        self.rollback_count = 0

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rollback_count += 1


class _CopyCursor:
    def __init__(self):
        self._fetchone_rows = [(18, 7, "client.test", "Client Test", "2026-09-23", Decimal("20"), "Note", "DE-2026-18", Decimal("0"), False)]
        self._fetchall_rows = [[
            (41, "product", "Produit", "Info", "U", Decimal("2"), Decimal("500"), Decimal("0"), 1),
            (42, "section", "Pose", "", "", None, None, None, 2),
            (43, "service", "Installation", "", "ENS", Decimal("1"), Decimal("100"), Decimal("10"), 3),
        ]]

    def execute(self, _sql, _params=None):
        pass

    def fetchone(self):
        return self._fetchone_rows.pop(0)

    def fetchall(self):
        return self._fetchall_rows.pop(0)


class _CopyDatabase(Database):
    def __init__(self):
        super().__init__()
        self.cursor = _CopyCursor()
        self.saved = None

    def save_facture_with_items(self, header, items, facture_id=None, user=None):
        self.saved = (header, items, facture_id, user)
        return {"facture_id": 31, "facture_number": "FA001/2026"}


class _PaymentCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return (9,)


class _PaymentDatabase(Database):
    def __init__(self):
        super().__init__()
        self.cursor = _PaymentCursor()
        self.conn = _Connection()

    def get_facture(self, _facture_id, user=None):
        return {"client_id": 7, "remaining": Decimal("100000.00")}


class _FacturePaymentMutationCursor:
    def __init__(self):
        self.calls = []
        self.result = None

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        normalized = " ".join(sql.split()).upper()
        self.result = (Decimal("20.00"),) if normalized.startswith("SELECT AMOUNT") else (9,)

    def fetchone(self):
        return self.result


class _FacturePaymentMutationDatabase(Database):
    def __init__(self):
        super().__init__()
        self.cursor = _FacturePaymentMutationCursor()
        self.conn = _Connection()

    def get_facture(self, _facture_id, user=None):
        return {"paid": Decimal("80.00"), "total_ttc": Decimal("100.00")}


class _MultiDraftDatabase(Database):
    def __init__(self, client_ids):
        super().__init__(); self.client_ids = client_ids

    def get_facture_draft_from_sale(self, sale_id, facture_type="normal", date=None, user=None):
        return {
            "client_id": self.client_ids[sale_id], "source_sale_id": sale_id, "date": "2026-09-23",
            "tva_rate": Decimal("20"), "notes": "", "source_devis": f"DE-{sale_id}",
            "facture_type": facture_type,
            "items": [{"item_type": "manual", "designation": f"Ligne {sale_id}", "quantity": 1,
                       "unit_price": Decimal("100"), "discount_percentage": 0}],
        }


class _CountingConnection:
    """Connection double that records commits so a read path can be proven read-only."""

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _AllocationCursor:
    """Answers the exact queries the allocation guard and backfill issue."""

    def __init__(self, database):
        self.db = database
        self.updates = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("SELECT FACTURE_ID, SALE_ID FROM FACTURE_SOURCES"):
            self.rows = [(fid, sid) for fid, sids in self.db.pending_sources.items()
                         for sid in sids]
        elif normalized.startswith("SELECT SALE_ID FROM FACTURE_SOURCES"):
            self.rows = [(sid,) for sid in self.db.invoice_sources[int(params[0])]]
        elif normalized.startswith("UPDATE FACTURE_SOURCES"):
            self.updates.append((sql, params))
            self.rowcount = 1
            self.rows = []
        else:
            self.rows = []

    def fetchall(self):
        return self.rows


class _AmbiguousAllocationDatabase(Database):
    """Database double reproducing legacy invoices that have no stored split."""

    def __init__(self, allocations, invoice_sources=None):
        super().__init__()
        self.allocations = allocations
        self.invoice_sources = invoice_sources or {}
        self.pending_sources = {}
        self.facture_totals = {}
        self.cursor = _AllocationCursor(self)
        self.conn = _CountingConnection()

    def _source_allocation_rows(self, source_ids, exclude_facture_id=None):
        requested = set(source_ids)
        return [(sid, alloc, fid) for sid, rows in self.allocations.items()
                for alloc, fid in rows if sid in requested]

    def _facture_totals(self, facture_id):
        return {"total_ttc": self.facture_totals[facture_id]}


class _ListResilientDatabase(Database):
    """One invoice raises while loading; the other must still be listed."""

    class _Cursor:
        def __init__(self, rows):
            self.rows = rows
            self._rows = None

        def execute(self, sql, params=None):
            self._rows = self.rows

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

    class _Conn:
        def rollback(self):
            pass

    def __init__(self):
        super().__init__()
        header = (2, "FA-LEGACY/2026", None, "DE-1", 7, "c", "C", "", "", None,
                  "2026-09-23", "normal", Decimal("20"), Decimal("0"), True,
                  Decimal("1000.00"), Decimal("0"), "", None, None)
        self.cursor = self._Cursor([(1,), (2,)])
        self.conn = self._Conn()
        self._headers = {2: header}

    def get_facture(self, facture_id, user=None):
        if int(facture_id) == 1:
            return {"id": 1, "facture_number": "FA-OK/2026"}
        raise ValueError("legacy row cannot be rebuilt")

    def _facture_header_fallback(self, facture_id):
        row = self._headers.get(int(facture_id))
        if not row:
            return None
        fields = ("id", "facture_number", "source_sale_id", "source_devis", "client_id",
                  "client_username", "client_name", "client_address", "client_city", "client_ice",
                  "date", "facture_type", "tva_rate", "remise", "remise_includes_line_discounts",
                  "selected_total_ttc", "previous_advance_ttc", "notes", "created_at", "updated_at")
        return dict(zip(fields, row), read_error=True,
                    already_invoiced_ttc=to_decimal(row[16] or 0))


class FactureEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_manual_facture_keeps_decimal_line_data_and_live_totals(self):
        database = _FactureDatabase()
        dialog = FactureEditor(database)
        _wait_until(lambda: dialog._catalog_ready)
        try:
            dialog.items.cellWidget(0, 0).setCurrentIndex(dialog.items.cellWidget(0, 0).findData("service"))
            dialog.items.cellWidget(0, 1).setCurrentText("Pose")
            dialog._set_client(7)
            dialog.items.item(0, 4).setText("12")
            dialog.items.item(0, 5).setText("15")
            dialog.items.item(0, 6).setText("5")
            dialog.update_totals()
            self.assertEqual(dialog.total_ttc.text(), "Total TTC: 205.20 MAD")
            dialog.save()
            _wait_until(lambda: not dialog._saving)
            header, items, facture_id = database.saved
            self.assertEqual(header["client_id"], 7)
            self.assertEqual(facture_id, None)
            self.assertEqual(items[0]["item_type"], "service")
            self.assertEqual(items[0]["discount_percentage"], "5")
        finally:
            dialog.reject()

    def test_amount_in_words_for_invoice_totals(self):
        self.assertEqual(amount_to_words(Decimal("200000")), "DEUX CENT MILLE DIRHAMS")
        self.assertEqual(amount_to_words(Decimal("700000")), "SEPT CENT MILLE DIRHAMS")
        self.assertEqual(
            amount_to_words(Decimal("1250.50")),
            "MILLE DEUX CENT CINQUANTE DIRHAMS ET CINQUANTE CENTIMES",
        )

    def test_only_confirmed_sales_are_financially_active(self):
        self.assertFalse(is_financially_active("on_hold"))
        self.assertFalse(is_financially_active("pending"))
        self.assertTrue(is_financially_active("confirmed"))
        self.assertTrue(is_financially_active("finished"))

    def test_facture_rpc_permissions_are_explicit(self):
        user = {"is_superadmin": False, "permissions": {
            "Factures": {"read": True, "write": True, "delete": False},
            "Sales": {"read": True, "write": False, "delete": False},
        }}
        self.assertTrue(_check_permission(user, "list_factures", [], {})[0])
        self.assertTrue(_check_permission(user, "create_facture_from_sale", [], {})[0])
        self.assertFalse(_check_permission(user, "delete_facture", [], {})[0])

    def test_additive_migration_creates_only_invoice_objects(self):
        database = Database()
        database.cursor = _Cursor()
        database.conn = _Connection()
        database._ensure_facture_tables()
        statements = "\n".join(sql for sql, _params in database.cursor.statements).upper()
        self.assertIn("CREATE TABLE IF NOT EXISTS FACTURES", statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS FACTURE_ITEMS", statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS FACTURE_SOURCES", statements)
        self.assertIn("ALTER TABLE PAYMENTS ADD COLUMN IF NOT EXISTS FACTURE_ID", statements)
        self.assertIn("FACTURES_NUMBER_UIDX", statements)
        self.assertNotIn("DROP TABLE", statements)
        self.assertTrue(database.conn.committed)
        self.assertEqual(database.conn.rollback_count, 0)

    def test_tab_participates_in_main_window_refresh_lifecycle(self):
        tab = FacturesTab(_FactureDatabase())
        tab.refresh_table(force=True)
        tab.refresh_on_tab_switch()
        _wait_until(lambda: tab._refresh_thread is None and not tab._refresh_pending)
        self.assertEqual(tab.table.rowCount(), 0)

    def test_invoice_rpc_payloads_are_json_safe(self):
        payload = RemoteDatabase._json_safe({"total": Decimal("1200.00"), "none": None})
        self.assertEqual(payload, {"total": "1200.00", "none": None})

    def test_client_catalog_normalizes_the_canonical_primary_key(self):
        database = Database()
        cursor = _CatalogCursor([(7, "client.test", "Client Test", "Rue Test", "ICE7")])
        database.cursor = cursor
        catalog = database.get_sale_catalog(False, False, include_clients=True)
        self.assertEqual(catalog["clients"], [
            {"id": 7, "username": "client.test", "name": "Client Test", "address": "Rue Test", "ice": "ICE7"}
        ])
        self.assertIn("SELECT id, username, name, address, ice FROM clients", cursor.sql)

    def test_client_picker_keeps_the_catalog_outside_the_editor(self):
        empty = FactureEditor(_FactureDatabase([]))
        self.assertTrue(empty.client.isReadOnly())
        self.assertEqual(empty.client.text(), "")
        empty.reject()
        dialog = FactureEditor(_FactureDatabase([
            {"id": 1, "name": None, "username": "alpha"},
            {"id": 2, "name": "Beta SARL", "username": None},
            {"id": 3, "name": None, "username": None},
        ]))
        _wait_until(lambda: dialog._catalog_ready)
        try:
            self.assertEqual(set(dialog.client_records), {1, 2, 3})
            dialog._set_client(2)
            self.assertEqual(dialog.client.text(), "Beta SARL")
        finally:
            dialog.reject()

    def test_existing_invoice_keeps_a_missing_client_snapshot_identity(self):
        database = _FactureDatabase([])
        facture = {"id": 8, "facture_number": "FA001/2026", "date": "2026-09-23", "facture_type": "normal",
                   "tva_rate": "20", "client_id": 91, "client_name": "Aptiv", "client_address": "Zone industrielle",
                   "client_city": "Tanger", "client_ice": "001", "notes": "", "items": []}
        dialog = FactureEditor(database, facture)
        _wait_until(lambda: dialog._catalog_ready)
        try:
            self.assertEqual(dialog.client_id, 91)
            self.assertIn("historique", dialog.client.text())
        finally:
            dialog.reject()

    def test_devis_selector_uses_visible_rows_not_an_id_prompt(self):
        database = _FactureDatabase()
        database.get_operation_summary_items = lambda *_args, **_kwargs: [{
            "ID": 18, "devis": "DE-2026-18", "client_name": "Aptiv", "date": "2026-09-23",
            "total_ht": Decimal("22725"), "total_ttc": Decimal("27270"), "state": "confirmed",
        }]
        dialog = DevisSelectorDialog(database)
        _wait_until(lambda: dialog.table.item(0, 1) is not None and dialog.table.item(0, 1).text() == "DE-2026-18")
        try:
            self.assertEqual(dialog.table.item(0, 1).text(), "DE-2026-18")
            dialog.table.item(0, 0).setCheckState(Qt.Checked); dialog.select()
            self.assertEqual(dialog.sale_ids, [18])
        finally:
            dialog.reject()

    def test_advance_and_balance_editors_generate_distinct_financial_lines(self):
        advance_draft = {
            "client_id": 7, "date": "2026-09-23", "tva_rate": Decimal("20"),
            "source_sale_ids": [18, 19], "source_devis": "DE-2026-18 / DE-2026-19",
            "selected_total_ttc": Decimal("500000"), "previous_advance_ttc": Decimal("0"),
            "remaining_ttc": Decimal("500000"), "items": [],
        }
        advance_db = _FactureDatabase(); advance = FactureEditor(advance_db)
        _wait_until(lambda: advance._catalog_ready)
        try:
            advance_draft["facture_type"] = "advance"; advance.load_draft(advance_draft); advance.advance_amount.setValue(200000); advance.save()
            _wait_until(lambda: not advance._saving)
            header, lines, _facture_id = advance_db.saved
            self.assertEqual(header["source_sale_ids"], [18, 19])
            self.assertEqual(lines[0]["unit_price"], "166666.67")
            self.assertIn("SUIVANT DEVIS N° DE-2026-18 / DE-2026-19", lines[0]["designation"])
        finally:
            advance.reject()
        balance_db = _FactureDatabase(); balance = FactureEditor(balance_db)
        _wait_until(lambda: balance._catalog_ready)
        try:
            balance_draft = {**advance_draft, "facture_type": "balance", "selected_total_ttc": Decimal("700000"),
                             "previous_advance_ttc": Decimal("600000"), "remaining_ttc": Decimal("100000")}
            balance.load_draft(balance_draft); balance.save()
            _wait_until(lambda: not balance._saving)
            _header, lines, _facture_id = balance_db.saved
            self.assertEqual(lines[0]["unit_price"], "83333.33")
            self.assertIn("SOLDE", lines[0]["designation"])
        finally:
            balance.reject()

    def test_multi_devis_rejects_different_clients_before_invoice_creation(self):
        database = _MultiDraftDatabase({18: 7, 19: 8})
        with self.assertRaisesRegex(ValueError, "même client"):
            database.get_facture_draft_from_sales([18, 19])

    def test_multi_devis_rejects_different_tva_before_invoice_creation(self):
        database = _MultiDraftDatabase({18: 7, 19: 7})
        original = database.get_facture_draft_from_sale
        database.get_facture_draft_from_sale = lambda sale_id, *args: {
            **original(sale_id, *args), "tva_rate": Decimal("20") if sale_id == 18 else Decimal("0"),
        }
        with self.assertRaisesRegex(ValueError, "même taux de TVA"):
            database.get_facture_draft_from_sales([18, 19])

    def test_proportional_source_allocation_is_deterministic_and_exact(self):
        self.assertEqual(Database._proportional_allocations({18: Decimal("40000"), 19: Decimal("60000")}, Decimal("30000")), {
            18: Decimal("12000.00"), 19: Decimal("18000.00"),
        })

    # ---- Legacy invoices with no stored per-Devis allocation ---------------
    # A pre-existing invoice spanning several Devis without a stored split must
    # never make invoices unreadable, and must only block a NEW balance calc.

    def test_ambiguous_legacy_allocation_never_raises_on_the_read_path(self):
        database = _AmbiguousAllocationDatabase(
            {18: [(None, 4)], 19: [(None, 4)], 20: [(None, 4)]}, {4: [18, 19, 20]})
        read = database.get_invoiced_total_for_sources([18, 19, 20], strict=False)
        self.assertTrue(read["ambiguous_facture_ids"])
        self.assertEqual(read["group_level"], True)

    def test_strict_calculation_refuses_to_guess_an_ambiguous_legacy_allocation(self):
        database = _AmbiguousAllocationDatabase(
            {18: [(None, 4)], 19: [(None, 4)], 20: [(None, 4)]}, {4: [18, 19, 20]})
        # A single Devis out of a multi-Devis legacy invoice cannot be resolved.
        with self.assertRaisesRegex(ValueError, "ancienne facture"):
            database.get_invoiced_total_for_sources([18], strict=True)

    def test_strict_calculation_accepts_the_exact_same_devis_group(self):
        database = _AmbiguousAllocationDatabase(
            {18: [(None, 4)], 19: [(None, 4)], 20: [(None, 4)]}, {4: [18, 19, 20]})
        database.facture_totals = {4: Decimal("50000")}
        result = database.get_invoiced_total_for_sources([18, 19, 20], strict=True)
        self.assertEqual(result["total_ttc"], Decimal("50000.00"))
        self.assertEqual(result["group_level"], True)

    def test_group_total_adds_every_ambiguous_legacy_invoice(self):
        database = _AmbiguousAllocationDatabase(
            {18: [(None, 4), (None, 5)], 19: [(None, 4), (None, 5)], 20: [(None, 4), (None, 5)]},
            {4: [18, 19, 20], 5: [18, 19, 20]})
        database.facture_totals = {4: Decimal("50000"), 5: Decimal("8000")}
        result = database.get_invoiced_total_for_sources([18, 19, 20], strict=True)
        self.assertEqual(result["total_ttc"], Decimal("58000.00"))
        self.assertEqual(result["ambiguous_facture_ids"], [4, 5])

    def test_allocation_result_stays_json_safe_for_remote_clients(self):
        database = _AmbiguousAllocationDatabase(
            {18: [(None, 4)], 19: [(None, 4)], 20: [(None, 4)]}, {4: [18, 19, 20]})
        database.facture_totals = {4: Decimal("50000")}
        result = database.get_invoiced_total_for_sources([18, 19, 20], strict=True)
        # A set would be serialized as a string by the RPC encoder's default=str.
        encoded = json.loads(json.dumps(result, default=str))
        self.assertEqual(encoded["ambiguous_facture_ids"], [4])

    def test_ambiguity_message_never_says_historique(self):
        # The user-facing wording must describe an old invoice, not call it
        # "facture historique".
        self.assertIn("ancienne facture", Database.AMBIGUOUS_ALLOCATION_MESSAGE)
        self.assertNotIn("historique", Database.AMBIGUOUS_ALLOCATION_MESSAGE)

    def test_reading_an_invoice_does_not_backfill_or_commit(self):
        database = _AmbiguousAllocationDatabase({18: [(None, 4)]}, {4: [18, 19, 20]})
        database.get_invoiced_total_for_sources([18], strict=False)
        self.assertEqual(database.conn.commits, 0)
        self.assertEqual(database.cursor.updates, [])

    def test_backfill_only_resolves_single_devis_legacy_invoices(self):
        database = _AmbiguousAllocationDatabase({18: [(None, 4), (None, 6)]}, {4: [18, 19, 20]})
        database.facture_totals = {4: Decimal("50000"), 6: Decimal("4000")}
        database.pending_sources = {4: [18, 19, 20], 6: [18]}
        database._backfill_unambiguous_source_allocations()
        # Only the unambiguous single-Devis invoice 6 got a stored split.
        self.assertEqual([call[1] for call in database.cursor.updates],
                         [(Decimal("4000.00"), 6, 18)])
        self.assertEqual(database.conn.commits, 1)

    def test_list_factures_keeps_a_row_whose_derived_data_cannot_be_rebuilt(self):
        database = _ListResilientDatabase()
        listed = database.list_factures()
        self.assertEqual([f["id"] for f in listed], [1, 2])
        self.assertEqual(listed[1]["read_error"], True)
        self.assertEqual(listed[1]["facture_number"], "FA-LEGACY/2026")

    def test_paid_balance_document_keeps_payment_balance_separate(self):
        facture = {
            "facture_number": "FA009/2026", "date": "2026-09-23", "facture_type": "balance",
            "client_name": "Aptiv", "items": [], "total_ht": Decimal("18612.00"),
            "vat_amount": Decimal("3722.40"), "total_ttc": Decimal("22334.40"),
            "selected_total_ttc": Decimal("100000"), "previous_advance_ttc": Decimal("77665.60"),
            "paid": Decimal("22334.40"), "remaining": Decimal("0"), "amount_in_words": "TEST",
        }
        rows = _document_data(facture, [], None)["total_rows"]
        # The balance document shows the FULL project value, not the balance
        # amount, and its payment lines are actual-payment based.
        self.assertIn(("Total TTC", "100 000,00 MAD", True), rows)
        self.assertIn(("DÉJÀ PAYÉ", "0,00 MAD", False), rows)
        self.assertIn(("PAYÉ", "22 334,40 MAD", False), rows)
        self.assertIn(("RESTE À PAYER", "77 665,60 MAD", True), rows)
        # Labels removed by the new layout.
        self.assertNotIn("SOLDE FACTURÉ", [row[0] for row in rows])
        self.assertNotIn("MONTANT GLOBAL DES DEVIS", [row[0] for row in rows])

    def test_advance_document_shows_project_totals_but_keeps_advance_amount(self):
        facture = {
            "facture_number": "FA013/2026", "date": "2026-09-23", "facture_type": "advance",
            "client_name": "Aptiv", "items": [], "total_ht": Decimal("2083.33"),
            "vat_amount": Decimal("416.67"), "total_ttc": Decimal("2500"),
            "selected_total_ht": Decimal("30000"), "selected_vat_amount": Decimal("6000"),
            "selected_total_ttc": Decimal("36000"),
            "paid": Decimal("0"), "remaining": Decimal("2500"), "amount_in_words": "TEST",
        }
        rows = _document_data(facture, [], None)["total_rows"]
        self.assertEqual(rows, [
            ("TOTAL HT", "30 000,00 MAD", False),
            ("TOTAL TVA", "6 000,00 MAD", False),
            ("MONTANT GLOBAL", "36 000,00 MAD", False),
            ("AVANCE À PAYER", "2 500,00 MAD", True),
        ])
        # The advance block stays simple: no PAYE / RESTE lines.
        self.assertNotIn("PAYÉ", [row[0] for row in rows])
        self.assertNotIn("RESTE À PAYER", [row[0] for row in rows])

    def test_balance_document_renders_source_devis_lines(self):
        facture = {
            "facture_number": "FA014/2026", "date": "2026-09-23", "facture_type": "balance",
            "client_name": "Aptiv", "total_ht": Decimal("18612.00"),
            "vat_amount": Decimal("3722.40"), "total_ttc": Decimal("22334.40"),
            "selected_total_ht": Decimal("30000"), "selected_vat_amount": Decimal("6000"),
            "selected_total_ttc": Decimal("36000"),
            "previous_paid_ttc": Decimal("2500"), "current_paid_ttc": Decimal("0"),
            "project_remaining_to_pay": Decimal("33500"),
            "paid": Decimal("0"), "remaining": Decimal("22334.40"), "amount_in_words": "TEST",
            "items": [{"item_type": "manual", "designation": "SOLDE SUR TRAVAUX", "quantity": 1,
                       "unit_price": Decimal("100"), "discount_percentage": 0}],
            "sources": [{"sale_id": 38, "devis": "DE-2026-38", "allocated_ttc": Decimal("33500")}],
            "source_items": [
                {"source_sale_id": 38, "item_type": "product", "designation": "Product A",
                 "information": "", "unit": "U", "quantity": Decimal("2"),
                 "unit_price": Decimal("100"), "discount_percentage": 0, "sort_order": 1},
                {"source_sale_id": 38, "item_type": "section", "designation": "Porte",
                 "quantity": None, "unit_price": None, "discount_percentage": 0, "sort_order": 2},
                {"source_sale_id": 38, "item_type": "service", "designation": "Service A",
                 "information": "sur site", "unit": "ENS", "quantity": Decimal("1"),
                 "unit_price": Decimal("500"), "discount_percentage": 0, "sort_order": 3},
            ],
        }
        data = _document_data(facture, [], None)
        rendered = [item["designation"] for item in data["items"]]
        self.assertEqual(rendered, ["DEVIS N° DE-2026-38", "Product A", "Porte", "Service A"])
        self.assertNotIn("SOLDE SUR TRAVAUX", rendered)
        self.assertIn(("RESTE À PAYER", "33 500,00 MAD", True), data["total_rows"])

    def test_main_list_keeps_payment_amounts_in_the_payment_screen(self):
        tab = FacturesTab(_FactureDatabase())
        self.assertEqual([tab.table.horizontalHeaderItem(i).text() for i in range(tab.table.columnCount())], [
            "ID", "Facture N°", "Type", "Client", "Date", "Devis source", "Total TTC", "Statut",
        ])
        _wait_until(lambda: tab._refresh_thread is None and not tab._refresh_pending)

    def test_preview_defaults_to_fit_page_without_a_scroll_area(self):
        facture = {"facture_number": "FA001/2026", "date": "2026-09-23", "client_name": "Aptiv",
                   "client_address": "Adresse", "client_city": "Tanger", "client_ice": "ICE", "items": [],
                   "total_ht": Decimal("0"), "vat_amount": Decimal("0"), "total_ttc": Decimal("0"),
                   "paid": Decimal("0"), "remaining": Decimal("0"), "amount_in_words": "ZÉRO DIRHAM"}
        pages, _geometry = render_facture_preview_pages(facture, [])
        dialog = FacturePreviewDialog(pages)
        try:
            dialog.show(); self.app.processEvents()
            self.assertTrue(dialog.isMaximized())
            self.assertEqual(dialog.zoom, 0)
            self.assertLessEqual(dialog.page.pixmap().height(), dialog.page.height())
            self.assertLessEqual(dialog.page.pixmap().width(), dialog.page.width())
        finally:
            dialog.close()

    def test_company_profile_data_renders_without_empty_legal_labels(self):
        profile = ProfileClass("test")
        profile.set_values({
            "company name": "LAMIDAP - S.A.R.L", "address": "288, Zone Industrielle Gzenaya\n90000 Tanger",
            "phone": "00 212 539 39 45 60", "fax": "00 212 539 39 45 59",
            "email": "lamidap@lamidap.com", "website": "www.lamidap.com",
            "ice": "000066710000023", "patente": "52981388", "if number": "04909316",
            "rc": "31073", "cnss": "7412042", "bank name": "ATTIJARI WAFA BANQUE - CENTRE D'AFFAIRE",
            "bank account": "1370A000000023", "bank agency": "GZENAYA Z-F",
        })
        facture = {"facture_number": "FA001/2026", "date": "2026-09-23", "client_name": "Aptiv",
                   "items": [], "total_ht": Decimal("0"), "vat_amount": Decimal("0"), "total_ttc": Decimal("0"),
                   "paid": Decimal("0"), "remaining": Decimal("0"), "amount_in_words": "ZÉRO DIRHAM"}
        data = _document_data(facture, [], profile)
        self.assertIn("Fax : 00 212 539 39 45 59", data["contact"])
        self.assertEqual(data["website"], "www.lamidap.com")
        self.assertIn("ICE: 000066710000023", "\n".join(data["legal_lines"]))
        self.assertIn("COMPTE N°: 1370A000000023", data["bank_line"])
        empty = ProfileClass("empty")
        empty_data = _document_data(facture, [], empty)
        self.assertEqual(empty_data["legal_lines"], [])
        self.assertEqual(empty_data["bank_line"], "")

    def test_printable_document_uses_a4_width_and_contains_payment_reference(self):
        facture = {"facture_number": "FA001/2026", "date": "2026-09-23", "client_name": "Aptiv",
                   "client_address": "Adresse", "client_city": "Tanger", "client_ice": "ICE", "source_devis": "DE-1",
                   "items": [{"item_type": "manual", "designation": "Avance", "unit": "ENS", "quantity": 1,
                              "unit_price": Decimal("166666.67"), "discount_percentage": 0}],
                   "total_ht": Decimal("166666.67"), "vat_amount": Decimal("33333.33"), "total_ttc": Decimal("200000"),
                   "paid": Decimal("100000"), "remaining": Decimal("100000"), "amount_in_words": "DEUX CENT MILLE DIRHAMS"}
        pages, geometry = render_facture_preview_pages(
            facture, [{"method": "Chèque", "amount": Decimal("100000"), "reference": "1300019"}]
        )
        self.assertEqual(len(pages), 1)
        self.assertAlmostEqual(geometry["printable_mm"].width(), 182, places=1)
        self.assertAlmostEqual(geometry["printable_px"].width() / geometry["page_px"].width(), 182 / 210, places=2)

    def test_create_from_devis_copies_an_independent_snapshot_payload(self):
        database = _CopyDatabase()
        result = database.create_facture_from_sale(18, "advance", user={"id": 3})
        header, items, facture_id, user = database.saved
        self.assertEqual(result["facture_id"], 31)
        self.assertIsNone(facture_id)
        self.assertEqual(user, {"id": 3})
        self.assertEqual(header["client_id"], 7)
        self.assertEqual(header["source_sale_id"], 18)
        self.assertEqual(header["source_devis"], "DE-2026-18")
        self.assertEqual(header["facture_type"], "advance")
        self.assertEqual(items[0]["source_sale_item_id"], 41)
        self.assertEqual(items[0]["unit"], "U")
        self.assertEqual(items[1]["item_type"], "section")
        self.assertEqual(items[2]["discount_percentage"], Decimal("10"))

    def test_facture_payment_cannot_overallocate_the_shared_ledger(self):
        database = _PaymentDatabase()
        with self.assertRaisesRegex(ValueError, "remaining invoice balance"):
            database.add_facture_payment(5, "100000.01", "2026-09-23")
        payment_id = database.add_facture_payment(5, "100000.00", "2026-09-23", "Virement")
        self.assertEqual(payment_id, 9)
        self.assertTrue(database.conn.committed)
        self.assertIn("INSERT INTO payments", database.cursor.calls[-1][0])

    def test_facture_payment_edit_and_delete_are_invoice_scoped_and_safe(self):
        database = _FacturePaymentMutationDatabase()
        self.assertEqual(database.update_facture_payment(5, 9, "20.00", "2026-09-26", "Chèque", "CHQ-1", "Note"), 9)
        update_sql, update_params = database.cursor.calls[-1]
        self.assertIn("UPDATE payments SET amount", update_sql)
        self.assertEqual(update_params[-2:], (9, 5))
        with self.assertRaisesRegex(ValueError, "remaining invoice balance"):
            database.update_facture_payment(5, 9, "50.01", "2026-09-26")
        self.assertEqual(database.delete_facture_payment(5, 9), 9)
        delete_sql, delete_params = database.cursor.calls[-1]
        self.assertIn("DELETE FROM payments WHERE id", delete_sql)
        self.assertEqual(delete_params, (9, 5))


if __name__ == "__main__":
    unittest.main()
