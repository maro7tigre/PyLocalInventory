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
from ui.tabs.sales_tab import SalesEditDialog
from ui.widgets.parameters_widgets import ParameterWidgetFactory
from ui.widgets.autocomplete_widgets import AutoExpandingTextEdit


class _Values:
    def __init__(self, values):
        self.values = values
        self.config_path = os.path.join(tempfile.gettempdir(), "profile", "config.json")

    def get_value(self, key):
        return self.values.get(key)


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
        self.assertIn('<strong class="item-name">Transport</strong><span class="item-detail"> Casablanca to Tanger</span>', data["items"])
        self.assertNotIn(" — ", data["items"])
        self.assertEqual(data["total_ht"], "125,20")

    def test_sale_form_updates_subtotal_vat_and_total(self):
        dialog = SalesEditDialog(None, None)
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
        self.assertAlmostEqual(ParameterWidgetFactory.get_widget_value(dialog.total_widget), 150.24)

    def test_connected_client_report_is_created_in_local_writable_directory(self):
        RemoteDatabase = type("RemoteDatabase", (), {})
        sale = _Values({"id": 9, "client_name": "Network Client"})
        sale.database = RemoteDatabase()
        profile = _Values({"company name": "Network Company"})
        manager = type("Manager", (), {"selected_profile": profile})()
        dialog = ReportsDialog(sale, manager)
        dialog._generate_html_content = lambda _kind: "<html><body>client report</body></html>"

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


if __name__ == "__main__":
    unittest.main()
