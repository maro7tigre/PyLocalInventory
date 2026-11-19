import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QValidator
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QStyleOptionViewItem

from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from ui.dialogs.edit_dialogs.unknown_item_review_dialog import UnknownItemReviewDialog
from ui.widgets.operations_table import OperationsTableWidget


class _CatalogCursor:
    def __init__(self):
        self.row = None
        self.queries = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        self.queries.append((normalized, params))
        if "from products" in normalized:
            self.row = (11, "Shared Name", 18)
        elif "from services" in normalized:
            self.row = (22, "Shared Name", 35)
        else:
            self.row = None

    def fetchone(self):
        return self.row


class _Database:
    def __init__(self):
        self.cursor = _CatalogCursor()


class _ServiceOnlyCursor(_CatalogCursor):
    def execute(self, sql, params=()):
        normalized = " ".join(sql.lower().split())
        self.queries.append((normalized, params))
        if "from products" in normalized:
            self.row = None
        elif "from services" in normalized:
            self.row = (22, "Known Service", 35)
        else:
            self.row = None


class _ReviewResult:
    decisions = []

    def __init__(self, _items, _parent=None):
        pass

    def exec(self):
        return QDialog.Accepted

    def get_decisions(self):
        return list(self.decisions)


class _ReviewDatabase:
    def __init__(self):
        self.cursor = object()
        self.sale_catalog = {"products": [], "services": []}
        self.permission_checks = []

    def has_permission(self, section, permission):
        self.permission_checks.append((section, permission))
        return True


class CatalogSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_explicit_service_keeps_service_id_and_price_and_skips_stock(self):
        database = _Database()
        widget = OperationsTableWidget(
            SalesItemClass,
            database=database,
            columns=[
                "item_type", "product_name", "quantity", "unit_price",
                "subtotal", "delete_action",
            ],
            highlight_stock_exceed=True,
        )
        type_col = widget.data_manager.table_columns.index("item_type")
        name_col = widget.data_manager.table_columns.index("product_name")
        price_col = widget.data_manager.table_columns.index("unit_price")
        selector = widget.table.cellWidget(0, type_col)
        name = widget.table.cellWidget(0, name_col)
        selector.setCurrentIndex(selector.findData("service"))
        name.setText("Shared Name")

        widget.event_handler._handle_product_selection(0, "Shared Name")
        row = widget.data_manager.extract_row_data(widget.table, 0)

        self.assertEqual(row["item_type"], "service")
        self.assertEqual(row["service_id"], 22)
        self.assertNotIn("product_id", row)
        self.assertEqual(widget.table.item(0, price_col).text(), "35")
        self.assertIsNone(widget.event_handler.get_row_stock_state(0))
        widget.close()

    def test_type_selector_offers_product_service_keep_only_and_section(self):
        widget = OperationsTableWidget(
            SalesItemClass,
            database=_Database(),
            columns=["item_type", "product_name", "quantity", "unit_price"],
        )
        type_col = widget.data_manager.table_columns.index("item_type")
        selector = widget.table.cellWidget(0, type_col)

        self.assertEqual(selector.count(), 4)
        self.assertEqual(
            [selector.itemData(index) for index in range(selector.count())],
            ["product", "service", "manual", "section"],
        )
        widget.close()

    def test_unknown_review_offers_section_per_line_and_apply_to_all(self):
        dialog = UnknownItemReviewDialog([
            {"name": "IMMEUBLES", "quantity": 1, "unit_price": 0},
            {"name": "VILLAS", "quantity": 1, "unit_price": 0},
        ])
        expected = ["product", "service", "manual", "section", "cancel"]
        row_selector = dialog.table.cellWidget(0, 4)

        self.assertEqual(
            [row_selector.itemData(index) for index in range(row_selector.count())],
            expected,
        )
        self.assertEqual(
            [dialog.bulk_selector.itemData(index)
             for index in range(dialog.bulk_selector.count())],
            expected,
        )
        dialog.bulk_selector.setCurrentIndex(dialog.bulk_selector.findData("section"))
        dialog._apply_to_all()
        self.assertEqual(
            [decision["action"] for decision in dialog.get_decisions()],
            ["section", "section"],
        )
        dialog.close()

    def test_mixed_unknown_review_keeps_section_product_and_manual_distinct(self):
        database = _ReviewDatabase()
        rows = [
            {"product_name": "IMMEUBLES", "quantity": 1, "unit_price": 0,
             "row_index": 1},
            {"product_name": "PORTE CHAMBRE", "quantity": 2,
             "unit_price": 2500, "row_index": 2},
            {"product_name": "OLD SPECIAL ITEM", "quantity": 10,
             "unit_price": 300, "row_index": 3},
        ]
        selected_types = []
        fake_dialog = SimpleNamespace(
            database=database,
            operation_obj=SimpleNamespace(
                section="Sales",
                get_value=lambda key: True if key == "is_historical" else None,
            ),
            items_table=SimpleNamespace(get_current_table_data=lambda: rows),
            pending_entities=[],
            _safe_widget_value=lambda key: "Known Client",
            _entity_exists=lambda section, value: True,
            _catalog_entity_exists=lambda item_type, name: False,
            _set_row_item_type=lambda row, item_type: selected_types.append(
                (row, item_type)
            ),
        )
        _ReviewResult.decisions = [
            {"name": "IMMEUBLES", "action": "section"},
            {"name": "PORTE CHAMBRE", "action": "product"},
            {"name": "OLD SPECIAL ITEM", "action": "manual"},
        ]

        with patch(
            "ui.dialogs.edit_dialogs.base_operation_dialog.UnknownItemReviewDialog",
            _ReviewResult,
        ), patch(
            "PySide6.QtWidgets.QInputDialog.getDouble",
            side_effect=[(0.0, True), (0.0, True)],
        ):
            result = BaseOperationDialog._handle_missing_references(fake_dialog)

        self.assertEqual(result, (True, False))
        self.assertEqual(selected_types, [
            (0, "section"), (1, "product"), (2, "manual"),
        ])
        self.assertEqual(len(fake_dialog.pending_entities), 1)
        self.assertEqual(fake_dialog.pending_entities[0]["type"], "product")
        self.assertEqual(fake_dialog.pending_entities[0]["name"], "PORTE CHAMBRE")
        self.assertNotIn(("Services", "write"), database.permission_checks)

    def test_existing_section_bypasses_unknown_item_review(self):
        database = _ReviewDatabase()
        fake_dialog = SimpleNamespace(
            database=database,
            operation_obj=SimpleNamespace(section="Sales"),
            items_table=SimpleNamespace(get_current_table_data=lambda: [{
                "item_type": "section", "product_name": "IMMEUBLES",
                "row_index": 1,
            }]),
            pending_entities=[],
            _safe_widget_value=lambda key: "Known Client",
            _entity_exists=lambda section, value: True,
            _catalog_entity_exists=lambda item_type, name: False,
        )

        with patch(
            "ui.dialogs.edit_dialogs.base_operation_dialog.UnknownItemReviewDialog"
        ) as review:
            result = BaseOperationDialog._handle_missing_references(fake_dialog)

        self.assertEqual(result, (True, False))
        review.assert_not_called()
        self.assertEqual(fake_dialog.pending_entities, [])

    def test_existing_service_selects_type_automatically(self):
        database = _Database()
        database.cursor = _ServiceOnlyCursor()
        widget = OperationsTableWidget(
            SalesItemClass,
            database=database,
            columns=[
                "item_type", "product_name", "quantity", "unit_price",
                "subtotal", "delete_action",
            ],
        )
        type_col = widget.data_manager.table_columns.index("item_type")
        name_col = widget.data_manager.table_columns.index("product_name")
        selector = widget.table.cellWidget(0, type_col)
        name = widget.table.cellWidget(0, name_col)
        name.setText("Known Service")

        widget.event_handler._handle_product_selection(0, "Known Service")

        self.assertEqual(selector.currentData(), "service")
        self.assertEqual(name.property("service_id"), 22)
        self.assertIsNone(name.property("product_id"))
        widget.close()

    def test_quantity_editor_allows_replacing_default_value(self):
        widget = OperationsTableWidget(
            SalesItemClass,
            database=_Database(),
            columns=["item_type", "product_name", "quantity", "unit_price"],
            highlight_stock_exceed=True,
        )
        qty_col = widget.data_manager.table_columns.index("quantity")
        delegate = widget.table.itemDelegateForColumn(qty_col)
        index = widget.table.model().index(0, qty_col)
        editor = delegate.createEditor(widget.table, QStyleOptionViewItem(), index)

        state, _, _ = editor.validator().validate("", 0)

        self.assertEqual(state, QValidator.Acceptable)
        delegate.destroyEditor(editor, index)
        widget.close()

    def test_add_section_has_title_only_and_blank_disabled_financial_cells(self):
        sale = SalesClass(0, None)
        widget = OperationsTableWidget(
            SalesItemClass,
            parent_operation=sale,
            columns=[
                "item_type", "product_name", "information", "quantity",
                "unit_price", "subtotal", "delete_action",
            ],
            highlight_stock_exceed=True,
        )

        widget.add_section_row()
        columns = widget.data_manager.table_columns
        selector = widget.table.cellWidget(0, columns.index("item_type"))
        name = widget.table.cellWidget(0, columns.index("product_name"))
        name.setText("IMMEUBLES")
        self.app.processEvents()

        self.assertEqual(selector.currentText(), "Section")
        self.assertEqual(selector.currentData(), "section")
        for key in ("quantity", "unit_price", "subtotal"):
            cell = widget.table.item(0, columns.index(key))
            self.assertEqual(cell.text(), "")
            self.assertFalse(bool(cell.flags() & Qt.ItemIsEditable))

        self.assertEqual(widget.get_current_table_data(), [{
            "item_type": "section",
            "product_name": "IMMEUBLES",
            "row_index": 1,
        }])
        section = widget.get_items_data()[0]
        self.assertEqual(section.get_value("item_type"), "section")
        self.assertIsNone(section.get_value("quantity"))
        self.assertIsNone(widget.event_handler.get_row_stock_state(0))
        widget.close()

    def test_delete_section_keeps_following_products_and_order(self):
        sale = SalesClass(1, None)
        section = SalesItemClass(11, None, sales_id=1)
        section.set_value("item_type", "section")
        section.set_value("product_name", "VILLAS")
        product_c = SalesItemClass(12, None, sales_id=1)
        product_c.set_value("item_type", "manual")
        product_c.set_value("product_name", "Product C")
        product_c.set_value("quantity", 2)
        product_c.set_value("unit_price", 50)
        product_d = SalesItemClass(13, None, sales_id=1)
        product_d.set_value("item_type", "manual")
        product_d.set_value("product_name", "Product D")
        product_d.set_value("quantity", 3)
        product_d.set_value("unit_price", 25)
        sale.items = [section, product_c, product_d]

        widget = OperationsTableWidget(
            SalesItemClass,
            parent_operation=sale,
            columns=[
                "item_type", "product_name", "quantity", "unit_price",
                "subtotal", "delete_action",
            ],
        )
        self.assertEqual(
            [row["product_name"] for row in widget.get_current_table_data()],
            ["VILLAS", "Product C", "Product D"],
        )

        widget._delete_row(0)

        self.assertEqual(
            [row["product_name"] for row in widget.get_current_table_data()],
            ["Product C", "Product D"],
        )
        widget.close()


if __name__ == "__main__":
    unittest.main()
