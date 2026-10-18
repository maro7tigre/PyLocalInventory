import sys
import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call
from decimal import Decimal

# Add root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog, SaveWorker, LoadWorker
from ui.widgets.operations_table import OperationsTableWidget
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import QEvent, QThread, QTimer
from PySide6.QtTest import QTest

app = QApplication.instance() or QApplication(sys.argv)

class DummyItem:
    def __init__(self, id, db):
        self.id = id
        self.section = "Sales_Items"
        self.db = db
        self.data = {}
    
    def get_value(self, key):
        return self.data.get(key)
        
    def set_value(self, key, val):
        self.data[key] = val

class DummyOperation:
    def __init__(self, id, db):
        self.id = id
        self.section = "Sales"
        self.database = db
        self.parameters = ["date", "state", "is_historical"]
        self.data = {"state": "pending", "is_historical": False}
        self.items = []

    def get_value(self, key):
        return self.data.get(key)
        
    def set_value(self, key, val):
        self.data[key] = val

    def get_visible_parameters(self, scope=None):
        return self.parameters
        
    def is_parameter_calculated(self, key):
        return False

    def load_database_data(self):
        self.data['loaded'] = True

class TestBaseOperationDialogAsync(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.sale_catalog = {
            "products": [{"id": 1, "name": "Prod A", "stock": 10}],
            "services": []
        }
        # Save/load error paths open MODAL QMessageBox dialogs that would
        # block forever in a headless test (no user to click). Auto-dismiss
        # every modal box so the async lifecycle - not the dialog UX - is
        # what these tests exercise.
        self.qmsg_patchers = [
            patch.object(QMessageBox, 'information', return_value=QMessageBox.Ok),
            patch.object(QMessageBox, 'critical', return_value=QMessageBox.Ok),
            patch.object(QMessageBox, 'warning', return_value=QMessageBox.Ok),
            patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes),
        ]
        for patcher in self.qmsg_patchers:
            patcher.start()

    def tearDown(self):
        for patcher in self.qmsg_patchers:
            patcher.stop()
        self.db.get_sale_catalog.return_value = self.db.sale_catalog

    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QThread.start')
    @patch('core.database.Database')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.setup_ui')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.load_data')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.apply_theme')
    def test_load_worker_success(self, mock_theme, mock_load, mock_setup, mock_db_class, mock_thread_start):
        mock_db_class.return_value.connect.return_value = True
        mock_db_class.return_value.get_sale_catalog.return_value = self.db.sale_catalog
        dialog = BaseOperationDialog(DummyOperation, DummyItem, operation_id=1, database=self.db)
        
        # Test worker (QThread.start is mocked so the worker only runs via the
        # explicit process() call below; the real thread would otherwise delete
        # the worker before we get here, racing this test).
        self.assertTrue(dialog.load_thread.isRunning() or not dialog.load_thread.isFinished())
        
        if dialog.load_worker:
            dialog.load_worker.process()
        
        lt = dialog.load_thread
        dialog._on_load_finished()
        if lt:
            lt.quit()
            lt.wait()
        
        self.assertTrue(dialog.operation_obj.data.get('loaded'))
        self.assertEqual(dialog.database.sale_catalog["products"][0]["name"], "Prod A")

    def test_remote_load_completion_runs_on_gui_thread(self):
        class RemoteDatabase:
            def has_permission(self, *_args):
                return True

            def get_sale_catalog(self, **_kwargs):
                return {"products": [], "services": []}

        RemoteDatabase.__name__ = "RemoteDatabase"
        gui_thread = QThread.currentThread()
        callback_threads = []

        def setup_ui(dialog):
            dialog.parameter_widgets = {}
            dialog.remise_spinbox = None
            dialog.items_table = None

        def load_data(_dialog):
            callback_threads.append(QThread.currentThread())

        with patch.object(BaseOperationDialog, "setup_ui", setup_ui), patch.object(
            BaseOperationDialog, "apply_theme", lambda _dialog: None,
        ), patch.object(BaseOperationDialog, "load_data", load_data):
            dialog = BaseOperationDialog(DummyOperation, DummyItem, database=RemoteDatabase())
            thread = dialog.load_thread
            try:
                deadline = time.monotonic() + 2
                while not callback_threads and time.monotonic() < deadline:
                    app.processEvents()
                    QTest.qWait(2)
                self.assertTrue(callback_threads, "remote load callback did not run")
                self.assertEqual(callback_threads[0], gui_thread)
                self.assertIsNotNone(thread)
            finally:
                if thread is not None:
                    try:
                        self.assertTrue(thread.wait(2000), "load QThread did not stop")
                    except RuntimeError:
                        pass
                app.sendPostedEvents(None, QEvent.DeferredDelete)
                app.processEvents()
                dialog.close()

    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QThread.start')
    @patch('core.database.Database')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.setup_ui')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.load_data')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.apply_theme')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QMessageBox.warning')
    def test_load_worker_failure(self, mock_warn, mock_theme, mock_load, mock_setup, mock_db_class, mock_thread_start):
        mock_db_class.return_value.connect.return_value = True
        dialog = BaseOperationDialog(DummyOperation, DummyItem, operation_id=1, database=self.db)
        
        # Mock load_database_data to raise exception
        dialog.operation_obj.load_database_data = MagicMock(side_effect=Exception("Load error!"))
        
        # Force worker
        dialog.load_worker.process()
        
        # We manually call the connected slot because Qt signal dispatching in unittests across threads is tricky
        lt = dialog.load_thread
        dialog._on_load_error("Load error!")
        mock_warn.assert_called()
        if lt:
            lt.quit()
            lt.wait()

    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.setup_ui')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.load_data')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.apply_theme')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog.validate_data', return_value=[])
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QThread.start')
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog._handle_missing_references', return_value=(True, False))
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.BaseOperationDialog._confirm_sale_summary', return_value=True)
    @patch('ui.dialogs.edit_dialogs.base_operation_dialog.QMessageBox.information')
    def test_save_worker_success(self, mock_info, mock_confirm, mock_missing, mock_thread_start, mock_val, mock_theme, mock_load, mock_setup):
        dialog = BaseOperationDialog(DummyOperation, DummyItem, operation_id=1, database=self.db)
        dialog.items_table = MagicMock()
        dialog.items_table.get_items_data.return_value = []
        dialog.items_table.get_current_table_data.return_value = []
        dialog.parameter_widgets = {}
        dialog.save_btn = MagicMock()
        
        # Set up mock save
        dialog.database.save_sale_with_items = MagicMock(return_value={"sale_id": 1, "expected": 1, "saved": 1, "transaction": "committed"})
        
        # Trigger save
        dialog.save_changes()
        
        self.assertTrue(dialog._saving)
        dialog.save_btn.setEnabled.assert_called_with(False)
        
        # Process worker
        dialog.save_worker.process()
        
        st = dialog.save_thread
        dialog._on_save_finished({"sale_id": 1, "expected": 1, "saved": 1}, "updated")
        if st:
            st.quit()
            st.wait()
        
        self.assertFalse(dialog._saving)
        dialog.save_btn.setEnabled.assert_called_with(True)
        # Refs are cleared by _on_save_thread_finished (queued after the thread
        # stops), so simulate that delivery before asserting the cleanup.
        dialog._on_save_thread_finished()
        self.assertIsNone(dialog.save_worker)

class TestFactureEditorLoad(unittest.TestCase):
    def test_remote_editor_returns_before_catalog_and_preview_rpcs_finish(self):
        from ui.tabs.factures_tab import FactureEditor, _active_facture_editor_jobs

        gui_thread_id = threading.get_ident()
        catalog_started = threading.Event()
        release_catalog = threading.Event()

        class RemoteDatabase:
            def __init__(self):
                self.call_threads = []
                self.sale_catalog = {
                    "products": [{
                        "id": 1, "name": "Product", "price": "10", "stock": "5",
                    }],
                    "services": [],
                    "clients": [{"id": 7, "username": "client", "name": "Client"}],
                }

            def get_sale_catalog(self, *_args, **_kwargs):
                self.call_threads.append(threading.get_ident())
                catalog_started.set()
                if not release_catalog.wait(2):
                    raise TimeoutError("test did not release the catalog request")
                return self.sale_catalog

            def get_next_facture_preview(self):
                self.call_threads.append(threading.get_ident())
                time.sleep(0.03)
                return "FA-007/2026"

        RemoteDatabase.__name__ = "RemoteDatabase"
        database = RemoteDatabase()
        editor = FactureEditor(database)
        self.assertTrue(catalog_started.wait(2), "catalog request did not start")
        self.assertFalse(release_catalog.is_set(), "editor blocked until catalog RPC returned")
        thread = editor._catalog_thread
        self.assertIsNotNone(thread)

        editor.load_draft({
            "date": "2026-10-10", "facture_type": "normal", "tva_rate": 20,
            "notes": "Draft note", "client_id": 7,
            "source_devis": "DE-007/2026", "selected_total_ttc": 24,
            "previous_advance_ttc": 0, "remaining_ttc": 24,
            "items": [{
                "item_type": "product", "designation": "Product", "unit": "U",
                "quantity": "2", "unit_price": "10", "discount_percentage": "0",
            }],
        })
        release_catalog.set()
        self.assertTrue(thread.wait(2000), "FactureEditor load QThread did not stop")

        deadline = time.monotonic() + 2
        while not editor._catalog_ready and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(2)
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()

        self.assertTrue(editor._catalog_ready)
        self.assertEqual(len(database.call_threads), 2)
        self.assertEqual(len(set(database.call_threads)), 1)
        self.assertNotEqual(database.call_threads[0], gui_thread_id)
        self.assertEqual(editor.number.text(), "Aperçu: FA-007/2026")
        self.assertEqual(editor.client.text(), "Client")
        self.assertEqual(editor.notes.toPlainText(), "Draft note")
        self.assertEqual(editor.items.rowCount(), 1)
        self.assertTrue(editor.save_button.isEnabled())
        self.assertFalse(_active_facture_editor_jobs)
        editor.close()

    def test_local_editor_worker_uses_and_closes_a_dedicated_database(self):
        from ui.tabs.factures_tab import _FactureEditorLoadWorker

        class FakeDatabase:
            instances = []

            def __init__(self, profile_manager):
                self.profile_manager = profile_manager
                self.language = "en"
                self.registered_classes = {"Clients": object}
                self.connected = False
                self.closed = False
                self.calls = []
                self.__class__.instances.append(self)

            def connect(self, initialize_schema=False):
                assert initialize_schema is False
                self.connected = True
                return True

            def get_sale_catalog(self, *_args, **_kwargs):
                self.calls.append("catalog")
                return {"products": [], "services": [], "clients": []}

            def get_next_facture_preview(self):
                self.calls.append("preview")
                return "FA-007/2026"

            def close(self):
                self.closed = True

        FakeDatabase.instances.clear()
        source = FakeDatabase("profile")
        with patch("core.database.Database", FakeDatabase):
            received = []
            worker = _FactureEditorLoadWorker(source, fetch_preview=True)
            worker.loaded.connect(lambda catalog, preview: received.append((catalog, preview)))
            worker.run()

        self.assertEqual(len(FakeDatabase.instances), 2)
        background = FakeDatabase.instances[1]
        self.assertEqual(source.calls, [])
        self.assertTrue(background.connected and background.closed)
        self.assertEqual(background.language, source.language)
        self.assertIs(background.registered_classes, source.registered_classes)
        self.assertEqual(background.calls, ["catalog", "preview"])
        self.assertEqual(
            received, [({"products": [], "services": [], "clients": []}, {
                "preview": "FA-007/2026", "facture": None, "draft": None,
            })],
        )


class TestFactureAsyncDialogs(unittest.TestCase):
    @staticmethod
    def _pump_until(predicate, timeout=2000, desc=""):
        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            app.processEvents()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
            if predicate():
                return True
            time.sleep(0.005)
        app.processEvents()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        result = predicate()
        if not result and desc:
            print(f"[_pump_until timeout for: {desc}]", flush=True)
        return result

    def test_devis_selector_fetches_and_searches_off_gui_thread(self):
        from ui.tabs.factures_tab import DevisSelectorDialog, _active_facture_request_jobs

        started = threading.Event()
        release = threading.Event()
        gui_thread = threading.get_ident()

        class RemoteDatabase:
            def __init__(self):
                self.call_threads = []

            def get_operation_summary_items(self, *_args, **kwargs):
                self.call_threads.append(threading.get_ident())
                if kwargs.get("search_text") == "DE-2":
                    started.set()
                    if not release.wait(2):
                        raise TimeoutError("test did not release the Devis search")
                return [{
                    "id": 2, "devis": "DE-2", "client_name": "Client",
                    "date": "2026-10-01", "total_ht": 10,
                    "total_ttc": 12, "state": "pending",
                }]

        database = RemoteDatabase()
        dialog = DevisSelectorDialog(database)
        self.assertTrue(self._pump_until(lambda: dialog.table.rowCount() == 1, desc="initial rowCount"))
        dialog.search.setText("DE-2")
        self.assertTrue(
            self._pump_until(started.is_set, desc=f"started.is_set, text={dialog.search.text()}"), "Devis search did not start in the worker",
        )
        release.set()
        self.assertTrue(self._pump_until(
            lambda: dialog._facture_request_thread is None and
            dialog.table.item(0, 1) is not None and
            dialog.table.item(0, 1).text() == "DE-2",
            desc=f"search finished: thread={dialog._facture_request_thread}, item={(dialog.table.item(0, 1).text() if dialog.table.item(0, 1) else None)}"
        ))
        self.assertTrue(database.call_threads)
        self.assertTrue(all(thread_id != gui_thread for thread_id in database.call_threads))
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        self.assertFalse(_active_facture_request_jobs)
        dialog.close()

    def test_payment_dialog_load_and_write_are_async_and_single_attempt(self):
        from ui.tabs.factures_tab import FacturePaymentsDialog, _active_facture_request_jobs

        load_started = threading.Event()
        release_load = threading.Event()
        write_started = threading.Event()
        release_write = threading.Event()
        gui_thread = threading.get_ident()

        class RemoteDatabase:
            def __init__(self):
                self.call_threads = []
                self.write_calls = 0

            def get_facture(self, _facture_id):
                self.call_threads.append(threading.get_ident())
                load_started.set()
                if not release_load.wait(2):
                    raise TimeoutError("test did not release the payment load")
                return {"total_ttc": "12", "paid": "1", "remaining": "11", "status": "partial"}

            def get_facture_payments(self, _facture_id):
                self.call_threads.append(threading.get_ident())
                return [{"id": 4, "date": "2026-10-01", "amount": "1",
                         "method": "Cash", "reference": "", "notes": ""}]

            def add_facture_payment(self, *_args):
                self.write_calls += 1
                self.call_threads.append(threading.get_ident())
                write_started.set()
                if not release_write.wait(2):
                    raise TimeoutError("test did not release the payment write")
                return 5

        database = RemoteDatabase()
        dialog = FacturePaymentsDialog(database, 1)
        self.assertTrue(load_started.wait(2), "payment load did not start in the worker")
        self.assertEqual(dialog.table.rowCount(), 0)
        release_load.set()
        self.assertTrue(self._pump_until(
            lambda: dialog._facture_request_thread is None and dialog.table.rowCount() == 1,
            desc=f"payment initial load: thread={dialog._facture_request_thread}, rowCount={dialog.table.rowCount()}",
        ))
        self.assertIn("TTC: 12.00", dialog.summary.text())

        dialog.amount.setValue(2)
        dialog.add_payment()
        self.assertTrue(write_started.wait(2), "payment write did not start in the worker")
        self.assertEqual(database.write_calls, 1)
        release_write.set()
        self.assertTrue(self._pump_until(
            lambda: dialog._facture_request_thread is None and
            database.write_calls == 1 and dialog.table.rowCount() == 1 and
            not _active_facture_request_jobs,
            desc=f"payment write finish: thread={dialog._facture_request_thread}, write_calls={database.write_calls}, rows={dialog.table.rowCount()}, jobs={len(_active_facture_request_jobs)}",
            timeout=3000,
        ))
        self.assertEqual(database.write_calls, 1)
        self.assertTrue(database.call_threads)
        self.assertTrue(all(thread_id != gui_thread for thread_id in database.call_threads))
        dialog.close()


class TestOperationsTableCatalog(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db.sale_catalog = {
            "products": [
                {"id": 1, "name": "Apple", "stock": 50},
                {"id": 2, "name": "Banana", "stock": 10}
            ],
            "services": [
                {"id": 3, "name": "Delivery"}
            ]
        }
        
        self.table_widget = OperationsTableWidget(DummyItem, database=self.db)
        # Mock items_table inside dialog
        self.dialog = MagicMock()
        self.dialog.database = self.db
        self.dialog.operation_id = 1
        from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
        self.dialog._normalize_name = BaseOperationDialog._normalize_name
        self.validate_stock = BaseOperationDialog._validate_stock.__get__(self.dialog, BaseOperationDialog)
        self.catalog_entity_exists = BaseOperationDialog._catalog_entity_exists.__get__(self.dialog, BaseOperationDialog)

    def test_catalog_entity_exists(self):
        # Uses in-memory catalog, no SQL calls!
        self.db.cursor.execute = MagicMock()
        
        self.assertTrue(self.catalog_entity_exists("product", "Apple"))
        self.assertTrue(self.catalog_entity_exists("service", "Delivery"))
        self.assertFalse(self.catalog_entity_exists("product", "Orange"))
        
        # Assert NO SQL calls were made
        self.db.cursor.execute.assert_not_called()
        
    def test_validate_stock(self):
        item1 = MagicMock()
        item1.get_value.side_effect = lambda k: 1 if k == 'product_id' else ("Apple" if k == 'product_name' else 60)
        
        item2 = MagicMock()
        item2.get_value.side_effect = lambda k: 2 if k == 'product_id' else ("Banana" if k == 'product_name' else 5)
        
        self.db.cursor.execute = MagicMock()
        
        errors = self.validate_stock([item1, item2])
        self.assertEqual(len(errors), 1)
        self.assertIn("Apple", errors[0])
        
        # Assert NO SQL calls were made (uses catalog)
        self.db.cursor.execute.assert_not_called()
        
    def test_table_widget_stock_state_no_db(self):
        from ui.widgets.operations_table import TableEventHandler
        self.table_widget.event_handler.get_row_stock_state = TableEventHandler.get_row_stock_state.__get__(self.table_widget.event_handler, TableEventHandler)
        
        self.db.cursor.execute = MagicMock()
        
        self.table_widget.data_manager.table_columns = ['product_name', 'quantity']
        self.table_widget.table.setColumnCount(2)
        from PySide6.QtWidgets import QLineEdit
        prod_edit = QLineEdit("Apple")
        prod_edit.setProperty("product_id", 1)
        
        qty_edit = QLineEdit("60")
        
        # Mock cellWidget to return these
        self.table_widget.table.cellWidget = MagicMock(side_effect=lambda r, c: prod_edit if c == 0 else (qty_edit if c == 1 else None))
        
        self.table_widget.table.setRowCount(1)
        from PySide6.QtWidgets import QTableWidgetItem
        self.table_widget.table.setItem(0, 1, QTableWidgetItem("60"))
        
        state = self.table_widget.event_handler.get_row_stock_state(0)
        self.assertIsNotNone(state)
        req, stock, exceeded, name = state
        self.assertEqual(req, Decimal("60"))
        self.assertEqual(stock, Decimal("50"))
        self.assertTrue(exceeded)
        
        self.db.cursor.execute.assert_not_called()

if __name__ == '__main__':
    unittest.main()
