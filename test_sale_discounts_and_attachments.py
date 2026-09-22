import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from classes.sales_item_class import SalesItemClass
from core.attachments import AttachmentService
from core.calculations import calculate_line_subtotal, calculate_operation_totals


class TestSaleDiscounts(unittest.TestCase):
    def test_discounted_line_totals(self):
        self.assertEqual(calculate_line_subtotal(10, 100, 10), Decimal("900"))
        self.assertEqual(calculate_line_subtotal(4, 250, 4), Decimal("960"))
        self.assertEqual(calculate_line_subtotal(1, 500, "2.5"), Decimal("487.50"))
        self.assertEqual(calculate_line_subtotal(5, 20, 0), Decimal("100"))
        self.assertEqual(calculate_line_subtotal(5, 20, 100), Decimal("0"))

    def test_item_discount_precedes_global_remise(self):
        items_subtotal = (
            calculate_line_subtotal(10, 100, 10)
            + calculate_line_subtotal(4, 250, 4)
        )
        totals = calculate_operation_totals(items_subtotal, 100, 20)
        self.assertEqual(items_subtotal, Decimal("1860"))
        self.assertEqual(totals["total_ht"], Decimal("1760.00"))
        self.assertEqual(totals["vat_amount"], Decimal("352.00"))
        self.assertEqual(totals["total_ttc"], Decimal("2112.00"))

    def test_legacy_item_defaults_to_zero_discount(self):
        item = SalesItemClass(0, None)
        item.set_value("quantity", 2)
        item.set_value("unit_price", 125)
        self.assertEqual(item.calculate_subtotal(), Decimal("250"))

    def test_sales_item_save_method_is_a_class_method(self):
        database = MagicMock()
        database.add_item.return_value = 7
        item = SalesItemClass(0, database, sales_id=3)
        item.parameters["product_name"]["value"] = "Manual line"
        self.assertTrue(item.save_to_database())
        payload = database.add_item.call_args.args[0]
        self.assertEqual(payload["discount_percentage"], 0.0)


class TestClientAttachments(unittest.TestCase):
    def setUp(self):
        self.cursor = MagicMock()
        self.database = SimpleNamespace(cursor=self.cursor, conn=MagicMock())
        self.service = AttachmentService(self.database)
        self.service._ready = MagicMock()

    def test_general_client_attachment_queries_null_sale_id(self):
        self.cursor.fetchall.return_value = [
            (1, "client", 4, 4, None, "contract.pdf", "contract", "", "",
             "application/pdf", 5, "client/4/a.pdf", "2026-01-01", "2026-01-01")
        ]
        records = self.service.list("client", 4, "general")
        query = self.cursor.execute.call_args.args[0]
        self.assertIn("sale_id IS NULL", query)
        self.assertIsNone(records[0]["sale_id"])

    def test_client_list_includes_general_and_linked_sale_attachments(self):
        self.cursor.fetchall.return_value = [
            (1, "client", 4, 4, None, "contract.pdf", "contract", "", "",
             "application/pdf", 5, "client/4/contract.pdf", "2026-01-01", "2026-01-01"),
            (2, "sale", 15, None, 15, "sale.pdf", "sale", "", "",
             "application/pdf", 5, "sale/15/sale.pdf", "2026-01-01", "2026-01-01"),
        ]
        records = self.service.list("client", 4)
        query, params = self.cursor.execute.call_args.args
        self.assertIn("a.entity_type='sale'", query)
        self.assertEqual(params, (4, 4))
        self.assertEqual([record["sale_id"] for record in records], [None, 15])

    def test_sale_attachment_retrieval_is_unfiltered(self):
        self.cursor.fetchall.return_value = []
        self.service.list("sale", 9)
        query = self.cursor.execute.call_args.args[0]
        self.assertNotIn("sale_id IS NULL", query)

    def test_general_attachment_upload_persists_null_sale_id(self):
        self.cursor.fetchone.return_value = (12,)
        self.service._snapshot = MagicMock(return_value={"id": 12})
        self.service._record_change = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.attachments.storage_root", return_value=Path(directory)):
                attachment_id = self.service.upload(
                    "client", 4, "id.png", "iVBORw0KGgo=", sale_id=None
                )
        self.assertEqual(attachment_id, 12)
        query, values = self.cursor.execute.call_args.args
        self.assertIn("sale_id", query)
        self.assertEqual(values[2], 4)
        self.assertIsNone(values[3])
        self.assertEqual(len(values), 11)

    def test_general_attachment_deletion_uses_existing_service(self):
        self.service._record = MagicMock(return_value=("client", 4, "client/4/a.pdf"))
        self.service._record_change = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with patch("core.attachments.storage_root", return_value=Path(directory)):
                self.assertTrue(self.service.delete(12))
        self.cursor.execute.assert_called_with("DELETE FROM attachments WHERE id=%s", (12,))

    def test_client_sale_worker_treats_no_sales_as_empty_list(self):
        from ui.widgets.attachments_widget import _ClientSalesFetchWorker

        database = MagicMock()
        database.get_client_sales.return_value = []
        worker = _ClientSalesFetchWorker(database, 4)
        received, errors = [], []
        worker.finished.connect(received.append)
        worker.error.connect(errors.append)
        worker.run()
        self.assertEqual(received, [[]])
        self.assertEqual(errors, [])

    def test_load_worker_passes_catalog_to_gui_slot(self):
        from ui.dialogs.edit_dialogs.base_operation_dialog import LoadWorker

        database = MagicMock()
        database.__class__.__name__ = 'RemoteDatabase'
        database.has_permission.return_value = True
        database.get_sale_catalog.return_value = {'clients': [], 'products': [], 'services': []}
        worker = LoadWorker(None, database, fetch_catalog=True, fetch_devis_preview=False)
        received, errors = [], []
        worker.loaded.connect(received.append)
        worker.error.connect(errors.append)
        worker.process()
        self.assertEqual(received[0]['catalog']['clients'], [])
        self.assertEqual(errors, [])


class TestDecimalEditorDelegate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_discount_editor_commits_repeated_values(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
        from ui.widgets.operations_table import DecimalSpinBoxDelegate

        table = QTableWidget(1, 1)
        table.setItem(0, 0, QTableWidgetItem("0"))
        delegate = DecimalSpinBoxDelegate(2, 0, 100, table)
        index = table.model().index(0, 0)
        for value in (2.5, 10, 0, 100, 4.25) * 8:
            editor = delegate.createEditor(table, None, index)
            delegate.setEditorData(editor, index)
            editor.setValue(value)
            delegate.setModelData(editor, table.model(), index)
            self.app.processEvents()
            self.assertEqual(float(table.item(0, 0).text()), value)

    def test_sale_table_installs_bounded_discount_editor(self):
        from ui.widgets.operations_table import OperationsTableWidget, DecimalSpinBoxDelegate

        widget = OperationsTableWidget(
            SalesItemClass,
            database=MagicMock(),
            columns=["quantity", "unit_price", "discount_percentage", "subtotal"],
            highlight_stock_exceed=False,
        )
        discount_column = widget.data_manager.table_columns.index("discount_percentage")
        delegate = widget.table.itemDelegateForColumn(discount_column)
        self.assertIsInstance(delegate, DecimalSpinBoxDelegate)
        self.assertEqual(delegate.minimum, 0.0)
        self.assertEqual(delegate.maximum, 100.0)

if __name__ == "__main__":
    unittest.main()
