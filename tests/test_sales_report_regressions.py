import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt

from classes.sales_item_class import SalesItemClass
from ui.widgets.autocomplete_widgets import AutoCompleteLineEdit
from ui.dialogs.reports_dialog import ReportsDialog
from ui.dialogs.payment_dialog import PaymentDialog
from ui.dialogs.order_progress_dialog import OrderProgressDialog
from ui.dialogs.client_details_dialog import ClientDetailsDialog
from ui.tabs.sales_tab import SalesEditDialog
from ui.dialogs.edit_dialogs.base_operation_dialog import FINANCIAL_WIDGET_MAX
from ui.widgets.parameters_widgets import ParameterWidgetFactory
from ui.widgets.autocomplete_widgets import AutoExpandingTextEdit
from ui.widgets.operations_table import OperationsTableWidget
from ui.widgets.report_viewer import ReportViewerWidget


class _Values:
    def __init__(self, values):
        self.values = values
        self.config_path = os.path.join(tempfile.gettempdir(), "profile", "config.json")

    def get_value(self, key):
        return self.values.get(key)


class _PaymentCursor:
    def __init__(self):
        self._row = (Decimal("0"),)
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append(" ".join(sql.split()))
        return self

    def fetchone(self):
        return self._row


class _PaymentConnection:
    def commit(self):
        pass


class _PaymentDatabase:
    def __init__(self):
        self.cursor = _PaymentCursor()
        self.conn = _PaymentConnection()


class _CatalogCursor:
    def __init__(self):
        self._rows = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("select id, name, sale_price from products"):
            self._rows = [(11, "Known Product", Decimal("25"))]
        elif normalized.startswith("select id, name, unit_price from services"):
            self._rows = []
        elif normalized.startswith("select name from products"):
            self._rows = [("Known Product",)]
        elif normalized.startswith("select name, keywords from services"):
            self._rows = []
        elif normalized.startswith("select keywords from services"):
            self._rows = []
        elif normalized.startswith("select sum(quantity) from import_items"):
            self._rows = [(Decimal("80"),)]
        elif normalized.startswith("select sum(si.quantity)"):
            self._rows = [(Decimal("0"),)]
        else:
            self._rows = []
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


class _CatalogDatabase:
    def __init__(self):
        self.cursor = _CatalogCursor()


class _NoSelectionRpcCursor:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("Sale entry attempted a synchronous network query")


class _RemoteCatalogDatabase:
    def __init__(self):
        self.cursor = _NoSelectionRpcCursor()
        self.sale_catalog = {
            "products": [{
                "id": 11, "name": "Known Product", "price": "25",
                "preview_image": None, "stock": "80",
            }],
            "services": [],
        }


class _ReopenedSaleCursor:
    def __init__(self):
        self._rows = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("select username from clients"):
            self._rows = [("bnis",)]
        else:
            self._rows = []
        return self

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


class RemoteDatabase:
    """Minimal remote-shaped database used to exercise the Edit Sale load path."""

    language = "en"
    sale_catalog = {"products": [], "services": []}

    def __init__(self):
        self.cursor = _ReopenedSaleCursor()

    def has_permission(self, *_args):
        return True

    def get_sale_catalog(self, **_kwargs):
        return self.sale_catalog

    def get_items(self, section):
        if section != "Sales":
            return []
        return [{
            "ID": 75,
            "client_username": "bnis",
            "date": "2024-10-15",
            "devis": "DE-2024-298",
            "tva": 20.0,
            "remise": Decimal("342429.50"),
            "notes": "",
            "state": "pending",
            "is_historical": True,
        }]

    def get_items_by_operation_id(self, operation_id, section):
        if operation_id != 75 or section != "Sales_Items":
            return []
        return [
            {"ID": 1, "sales_id": 75, "item_type": "manual", "product_name": "A",
             "information": "", "quantity": Decimal("486"), "unit_price": Decimal("2580"), "production": 0},
            {"ID": 2, "sales_id": 75, "item_type": "manual", "product_name": "B",
             "information": "", "quantity": Decimal("117"), "unit_price": Decimal("2580"), "production": 0},
            {"ID": 3, "sales_id": 75, "item_type": "manual", "product_name": "C",
             "information": "", "quantity": Decimal("377"), "unit_price": Decimal("2580"), "production": 0},
            {"ID": 4, "sales_id": 75, "item_type": "manual", "product_name": "D",
             "information": "", "quantity": Decimal("195"), "unit_price": Decimal("3300"), "production": 0},
        ]


class SalesReportRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_decimal_quantity_is_not_truncated(self):
        item = SalesItemClass(0, None)
        item.set_value("quantity", "12,52")
        item.set_value("unit_price", 10)
        self.assertEqual(item.get_value("quantity"), Decimal("12.52"))
        self.assertEqual(item.get_value("subtotal"), Decimal("125.20"))

    def test_payment_dialog_accepts_decimal_sale_total(self):
        sale = _Values({
            "client_name": "Client", "client_username": "client", "date": "2026-07-20"
        })
        sale.id = 7
        sale.calculate_total_price = lambda: Decimal("439.20")
        dialog = PaymentDialog(sale, _PaymentDatabase(), config={"currency": None})
        self.assertEqual(dialog._total, 439.20)
        self.assertEqual(dialog._remaining_before, 439.20)
        self.assertEqual(dialog.currency, "MAD")
        dialog.close()

    def test_order_progress_accepts_decimal_sale_total(self):
        sale = _Values({
            "client_name": "Client", "client_username": "client",
            "date": "2026-07-20", "notes": ""
        })
        sale.id = 8
        sale.calculate_total_price = lambda: Decimal("439.20")
        sale.get_sales_items = lambda: []
        dialog = OrderProgressDialog(sale, _PaymentDatabase())
        self.assertEqual(dialog._remaining_item.text(), "439.20")
        dialog.close()

    def test_client_payment_migration_avoids_blocked_information_schema_query(self):
        database = _PaymentDatabase()
        holder = type("ClientDetailsHolder", (), {"database": database})()
        ClientDetailsDialog._ensure_payments_table(holder)
        sql = "\n".join(database.cursor.statements).lower()
        self.assertIn("add column if not exists sales_item_id", sql)
        self.assertNotIn("information_schema", sql)

    def test_highlighting_suggestion_does_not_replace_typed_words(self):
        edit = AutoCompleteLineEdit(options=["Transport Service Tanger"], allow_free_text=True)
        edit.setText("Transport Ser")
        edit.setCursorPosition(len(edit.text()))
        edit.completer.highlighted.emit("Transport Service Tanger")
        self.assertEqual(edit.text(), "Transport Ser")

    def test_actual_sale_editor_preserves_multiword_typing(self):
        edit = AutoExpandingTextEdit(options=["Transport Service Tanger"])
        edit.show()
        edit.setFocus()
        QTest.keyClicks(edit, "Transport Service Tanger")
        self.app.processEvents()
        self.assertEqual(edit.text(), "Transport Service Tanger")
        QTest.keyClick(edit, Qt.Key_Backspace)
        QTest.keyClicks(edit, "r")
        self.assertEqual(edit.text(), "Transport Service Tanger")

    def test_report_quantity_and_designation_keep_decimal_and_inline_detail(self):
        item = SalesItemClass(0, None)
        item.set_value("product_name", "Transport")
        item.set_value("information", "Casablanca to Tanger")
        item.set_value("quantity", "12.52")
        item.set_value("unit_price", "10")
        sale = _Values({"id": 7, "client_name": "Client", "date": "2026-07-17", "tva": 0})
        sale.items = [item]
        sale.database = None
        profile = _Values({"company name": "Test Company"})
        manager = type("Manager", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        data = dialog._extract_sales_data("devis")
        self.assertIn("<td>12.52</td>", data["items"])
        self.assertIn('<span class="product-item-name">Transport</span><span class="item-detail"> Casablanca to Tanger</span>', data["items"])
        self.assertNotIn('<strong class="item-name">Transport</strong>', data["items"])
        self.assertNotIn(" — ", data["items"])
        self.assertEqual(data["total_ht"], "125,20")

    def test_report_keeps_service_designation_bold(self):
        item = SalesItemClass(0, None)
        item.set_value("item_type", "service")
        item.set_value("service_id", 8)
        item.set_value("product_name", "porte de cuisine")
        item.set_value("quantity", 1)
        item.set_value("unit_price", 444)
        sale = _Values({
            "id": 8, "client_name": "Client", "date": "2026-07-27", "tva": 0
        })
        sale.items = [item]
        sale.database = None
        profile = _Values({"company name": "Test Company"})
        manager = type("Manager", (), {"selected_profile": profile})()
        data = ReportsDialog(sale, manager)._extract_sales_data("devis")
        self.assertIn(
            '<strong class="item-name">porte de cuisine</strong>', data["items"]
        )

    def test_sale_form_updates_subtotal_vat_and_total(self):
        dialog = SalesEditDialog(None, None)
        lt = dialog.load_thread
        if lt is not None:
            lt.wait(5000)
        self.app.processEvents()
        table = dialog.items_table.table
        columns = dialog.items_table.data_manager.table_columns
        name = table.cellWidget(0, columns.index("product_name"))
        name.setText("Transport Service")
        table.setItem(0, columns.index("quantity"), QTableWidgetItem("12.52"))
        table.setItem(0, columns.index("unit_price"), QTableWidgetItem("10"))
        self.app.processEvents()
        dialog.update_totals()
        self.assertEqual(table.item(0, columns.index("subtotal")).text(), "125.20")
        self.assertAlmostEqual(ParameterWidgetFactory.get_widget_value(dialog.subtotal_widget), 125.20)
        self.assertAlmostEqual(ParameterWidgetFactory.get_widget_value(dialog.vat_widget), 25.04)
        self.assertAlmostEqual(ParameterWidgetFactory.get_widget_value(dialog.total_ttc_widget), 150.24)

    def test_sale_section_button_adds_nonfinancial_row_without_changing_totals(self):
        dialog = SalesEditDialog(None, None)
        load_thread = dialog.load_thread
        if load_thread is not None:
            load_thread.wait(5000)
        self.app.processEvents()

        dialog.add_section_btn.click()
        table = dialog.items_table.table
        columns = dialog.items_table.data_manager.table_columns
        section_name = table.cellWidget(0, columns.index("product_name"))
        section_name.setText("IMMEUBLES")

        product_name = table.cellWidget(1, columns.index("product_name"))
        product_name.setText("Product A")
        table.setItem(1, columns.index("quantity"), QTableWidgetItem("2"))
        table.setItem(1, columns.index("unit_price"), QTableWidgetItem("100"))
        dialog.remise_spinbox.setValue(20)
        self.app.processEvents()
        dialog.update_totals()

        rows = dialog.items_table.get_current_table_data()
        self.assertEqual([row["product_name"] for row in rows], ["IMMEUBLES", "Product A"])
        self.assertEqual(rows[0], {
            "item_type": "section", "product_name": "IMMEUBLES", "row_index": 1,
        })
        self.assertEqual(dialog.subtotal_widget.value(), 200.0)
        self.assertEqual(dialog.total_ht_widget.value(), 180.0)
        self.assertEqual(dialog.vat_widget.value(), 36.0)
        self.assertEqual(dialog.total_ttc_widget.value(), 216.0)

    def test_devis_sections_are_bold_left_aligned_blank_and_ordered(self):
        def sale_item(item_type, name, quantity=None, unit_price=None):
            item = SalesItemClass(0, None)
            item.set_value("item_type", item_type)
            item.set_value("product_name", name)
            if item_type != "section":
                item.set_value("quantity", quantity)
                item.set_value("unit_price", unit_price)
            return item

        sale = _Values({
            "id": 77, "devis": "DE-2026-77", "client_name": "Client",
            "date": "2026-08-13", "tva": 0, "remise": 0,
        })
        sale.items = [
            sale_item("section", "IMMEUBLES"),
            sale_item("manual", "Product A", 100, 2000),
            sale_item("manual", "Product B", 50, 1000),
            sale_item("section", "VILLAS"),
            sale_item("manual", "Product C", 20, 5000),
        ]
        sale.database = None
        profile = _Values({"company name": "Test Company"})
        manager = type("Manager", (), {"selected_profile": profile})()

        data = ReportsDialog(sale, manager)._extract_sales_data("devis")
        items_html = data["items"]

        self.assertLess(items_html.index("IMMEUBLES"), items_html.index("Product A"))
        self.assertLess(items_html.index("Product B"), items_html.index("VILLAS"))
        self.assertLess(items_html.index("VILLAS"), items_html.index("Product C"))
        self.assertIn(
            '<tr class="sale-section-row"><td></td><td><strong '
            'class="sale-section-title" style="display:block;text-align:left">'
            'IMMEUBLES</strong></td><td></td><td></td><td></td></tr>',
            items_html,
        )
        self.assertNotIn('text-align:center">IMMEUBLES', items_html)
        self.assertEqual(data["total_ht"], "350 000,00")
        self.assertEqual(data["tva"], "0,00")
        self.assertEqual(data["total_ttc"], "350 000,00")

        facture_html = ReportsDialog(sale, manager)._extract_sales_data("facture")["items"]
        self.assertIn(
            '<tr class="sale-section-row"><td><strong '
            'class="sale-section-title" style="display:block;text-align:left">'
            'IMMEUBLES</strong></td><td></td><td></td><td></td></tr>',
            facture_html,
        )
        bdl_html = ReportsDialog(sale, manager)._extract_sales_data("bdl")["items"]
        self.assertIn(
            '<tr class="sale-section-row"><td></td><td><strong '
            'class="sale-section-title" style="display:block;text-align:left">'
            'IMMEUBLES</strong></td><td></td></tr>',
            bdl_html,
        )

    def test_sale_form_displays_totals_above_ten_million(self):
        dialog = SalesEditDialog(None, None)
        load_thread = dialog.load_thread
        if load_thread is not None:
            load_thread.wait(5000)
        self.app.processEvents()

        table = dialog.items_table.table
        columns = dialog.items_table.data_manager.table_columns
        name = table.cellWidget(0, columns.index("product_name"))
        name.setText("Large Manual Sale")
        table.setItem(0, columns.index("quantity"), QTableWidgetItem("20"))
        table.setItem(0, columns.index("unit_price"), QTableWidgetItem("1000000"))
        dialog.remise_spinbox.setValue(1_000_000.00)
        self.app.processEvents()
        dialog.update_totals()

        self.assertEqual(table.item(0, columns.index("subtotal")).text(), "20 000 000.00")
        self.assertEqual(dialog.subtotal_widget.value(), 20_000_000.00)
        self.assertEqual(dialog.remise_spinbox.value(), 1_000_000.00)
        self.assertEqual(dialog.total_ht_widget.value(), 19_000_000.00)
        self.assertEqual(dialog.vat_widget.value(), 3_800_000.00)
        self.assertEqual(dialog.total_ttc_widget.value(), 22_800_000.00)

        for widget in (
            dialog.subtotal_widget,
            dialog.total_ht_widget,
            dialog.vat_widget,
            dialog.total_ttc_widget,
        ):
            self.assertEqual(widget.spinbox.maximum(), FINANCIAL_WIDGET_MAX)
            self.assertNotEqual(widget.value(), 999999.0)
        self.assertEqual(dialog.remise_spinbox.maximum(), FINANCIAL_WIDGET_MAX)

        # The shared factory still keeps its conservative default for unrelated
        # numeric fields; only operation money widgets get the wider range.
        unrelated = ParameterWidgetFactory.create_widget({'type': 'float'})
        self.assertEqual(unrelated.spinbox.maximum(), 999999.0)

    def test_reopened_sale_displays_complete_multimillion_totals(self):
        dialog = SalesEditDialog(75, RemoteDatabase())
        load_thread = dialog.load_thread
        if load_thread is not None:
            load_thread.wait(5000)
        self.app.processEvents()
        dialog.update_totals()

        table = dialog.items_table.table
        columns = dialog.items_table.data_manager.table_columns
        subtotal_column = columns.index("subtotal")
        self.assertEqual(
            [table.item(row, subtotal_column).text() for row in range(4)],
            ["1 253 880.00", "301 860.00", "972 660.00", "643 500.00"],
        )
        self.assertEqual(dialog.subtotal_widget.value(), 3_171_900.00)
        self.assertEqual(dialog.remise_spinbox.value(), 342_429.50)
        self.assertEqual(dialog.total_ht_widget.value(), 2_829_470.50)
        self.assertEqual(dialog.vat_widget.value(), 565_894.10)
        self.assertEqual(dialog.total_ttc_widget.value(), 3_395_364.60)

    def test_large_sale_report_uses_complete_decimal_totals(self):
        item = SalesItemClass(0, None)
        item.set_value("product_name", "Large Manual Sale")
        item.set_value("quantity", "20")
        item.set_value("unit_price", "1000000")
        sale = _Values({
            "id": 76,
            "client_name": "Client",
            "date": "2026-08-13",
            "tva": 20,
            "remise": Decimal("1000000.00"),
        })
        sale.items = [item]
        sale.database = None
        profile = _Values({"company name": "Test Company"})
        manager = type("Manager", (), {"selected_profile": profile})()

        data = ReportsDialog(sale, manager)._extract_sales_data("devis")

        self.assertEqual(data["total_remise"], "1 000 000,00")
        self.assertEqual(data["total_ht"], "19 000 000,00")
        self.assertEqual(data["tva"], "3 800 000,00")
        self.assertEqual(data["total_ttc"], "22 800 000,00")

    def test_product_can_be_selected_before_typing_exact_quantity(self):
        table_widget = OperationsTableWidget(
            SalesItemClass,
            database=_RemoteCatalogDatabase(),
            columns=[
                "item_type", "product_name", "quantity",
                "unit_price", "subtotal", "delete_action",
            ],
            highlight_stock_exceed=True,
        )
        columns = table_widget.data_manager.table_columns
        name = table_widget.table.cellWidget(0, columns.index("product_name"))
        table_widget.show()
        name.setText("Known Product")
        table_widget.event_handler._on_product_selection_finished(0)
        self.app.processEvents()

        quantity_col = columns.index("quantity")
        delegate = table_widget.table.itemDelegateForColumn(quantity_col)
        editor = delegate.active_editors.get(0)
        self.assertIsNotNone(editor)
        QTest.keyClicks(editor, "4")
        QTest.keyClick(editor, Qt.Key_Tab)
        self.app.processEvents()

        quantity_item = table_widget.table.item(0, quantity_col)
        self.assertTrue(quantity_item.flags() & Qt.ItemIsEditable)
        row = table_widget.get_current_table_data()[0]
        self.assertEqual(row["quantity"], Decimal("4"))
        self.assertNotEqual(row["quantity"], Decimal("4000"))
        self.assertEqual(quantity_item.text(), "4")

        table_widget.row_factory._create_regular_cell(
            table_widget.table, 0, quantity_col, "quantity",
            _Values({"quantity": Decimal("4.000")}),
        )
        self.assertEqual(table_widget.table.item(0, quantity_col).text(), "4")
        table_widget.row_factory._create_regular_cell(
            table_widget.table, 0, quantity_col, "quantity",
            _Values({"quantity": Decimal("10.000")}),
        )
        self.assertEqual(table_widget.table.item(0, quantity_col).text(), "10")
        table_widget.close()

    def test_connected_client_report_is_created_in_local_writable_directory(self):
        RemoteDatabase = type("RemoteDatabase", (), {})
        sale = _Values({"id": 9, "client_name": "Network Client"})
        sale.database = RemoteDatabase()
        profile = _Values({"company name": "Network Company"})
        manager = type("Manager", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        dialog._generate_html_content = lambda _kind, database=None: "<html><body>client report</body></html>"

        def write_pdf(_html, output):
            with open(output, "wb") as stream:
                stream.write(b"%PDF-local-client-test")
            return output

        dialog._html_to_pdf = write_pdf
        with tempfile.TemporaryDirectory() as local_dir, patch(
            "ui.dialogs.reports_dialog.local_reports_dir", return_value=local_dir
        ):
            output = dialog._generate_report_sync("devis")
            self.assertTrue(os.path.isfile(output))
            self.assertEqual(os.path.dirname(output), local_dir)
            self.assertIn("connected client", dialog._report_context("devis", output, None))

    def test_connected_client_uses_host_report_profile_without_local_profile(self):
        RemoteDatabase = type("RemoteDatabase", (), {})
        remote = RemoteDatabase()
        remote.username = "network-user"
        remote.remote_profile = _Values({"company name": "Host Company"})
        sale = _Values({"id": 10, "client_name": "Network Client"})
        sale.database = remote
        manager = type("Manager", (), {"selected_profile": None})()
        dialog = ReportsDialog(sale, manager)
        dialog._generate_html_content = lambda _kind, database=None: "<html>host profile</html>"
        dialog._html_to_pdf = lambda _html, output: output

        with tempfile.TemporaryDirectory() as local_dir, patch(
            "ui.dialogs.reports_dialog.local_reports_dir", return_value=local_dir
        ), patch.object(dialog, "_cleanup_old_reports"):
            _html, output = dialog._prepare_report("devis")
        self.assertIs(dialog._active_profile, remote.remote_profile)
        self.assertEqual(os.path.dirname(output), local_dir)
        dialog.close()

    def test_printing_without_a_local_printer_fails_gracefully(self):
        viewer = ReportViewerWidget("Stock")
        viewer.set_report_data(["Product", "Quantity"], [["Known Product", 4]])
        with patch(
            "ui.widgets.report_viewer.QPrinterInfo.availablePrinterNames",
            return_value=[],
        ), patch(
            "ui.widgets.report_viewer.QMessageBox.warning"
        ) as warning:
            viewer.print_report()
        warning.assert_called_once()
        viewer.close()


if __name__ == "__main__":
    unittest.main()
