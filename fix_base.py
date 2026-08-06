import re

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Add threading imports
code = code.replace("from PySide6.QtCore import Qt", "from PySide6.QtCore import Qt, QThread, QObject, Signal, Slot, QTimer")

# 2. Add Workers
worker_code = """
class SaveWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, dialog, is_import):
        super().__init__()
        self.dialog = dialog
        self.is_import = is_import
        
    @Slot()
    def process(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            if self.is_import:
                res = self.dialog._save_import_atomically()
            else:
                res = self.dialog._save_sale_atomically()
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))

class LoadWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self, operation_obj, fetch_catalog):
        super().__init__()
        self.operation_obj = operation_obj
        self.fetch_catalog = fetch_catalog

    @Slot()
    def process(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            if self.operation_obj:
                self.operation_obj.load_database_data()
            if self.fetch_catalog and getattr(self.operation_obj.database, 'get_sale_catalog', None):
                self.operation_obj.database.sale_catalog = self.operation_obj.database.get_sale_catalog()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
"""
code = code.replace("logger = logging.getLogger(__name__)", "logger = logging.getLogger(__name__)\n" + worker_code)

# 3. Fix __init__
old_init = """        # Create or load operation object
        if operation_id:
            self.operation_obj = operation_class(operation_id, database)
            self.operation_obj.load_database_data()
            self.setWindowTitle(f"Edit {self.operation_obj.section[:-1]} - ID {operation_id}")
        else:
            self.operation_obj = operation_class(0, database)
            # Set default date to today for new operations
            if 'date' in self.operation_obj.parameters:
                self.operation_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
            self.setWindowTitle(f"New {self.operation_obj.section[:-1]}")
        
        # Setup UI
        self.setup_ui()
        self.load_data()
        self.apply_theme()
        
        # Auto-size dialog
        self.resize(900, 700)"""

new_init = """        # Create or load operation object
        if operation_id:
            self.operation_obj = operation_class(operation_id, database)
            self.setWindowTitle(f"Edit {self.operation_obj.section[:-1]} - ID {operation_id}")
        else:
            self.operation_obj = operation_class(0, database)
            # Set default date to today for new operations
            if 'date' in self.operation_obj.parameters:
                self.operation_obj.set_value("date", datetime.now().strftime("%Y-%m-%d"))
            self.setWindowTitle(f"New {self.operation_obj.section[:-1]}")
        
        # Setup UI
        self.setup_ui()
        self.apply_theme()
        
        self.setEnabled(False)
        self.setWindowTitle(self.windowTitle() + " (Loading...)")

        self.load_thread = QThread()
        self.load_worker = LoadWorker(
            self.operation_obj if operation_id else None, 
            fetch_catalog=not hasattr(database, "sale_catalog") or database.sale_catalog is None
        )
        self.load_worker.moveToThread(self.load_thread)
        self.load_thread.started.connect(self.load_worker.process)
        self.load_worker.finished.connect(self._on_load_finished)
        self.load_worker.error.connect(self._on_load_error)
        self.load_worker.finished.connect(self.load_thread.quit)
        self.load_worker.error.connect(self.load_thread.quit)
        self.load_thread.start()
        
        # Auto-size dialog
        self.resize(900, 700)
"""
code = code.replace(old_init, new_init)

# 4. Add _on_load_*
on_load = """
    def _on_load_finished(self):
        self.load_worker.deleteLater()
        self.load_thread.deleteLater()
        self.load_worker = None
        self.load_thread = None
        
        self.setEnabled(True)
        title = self.windowTitle().replace(" (Loading...)", "")
        self.setWindowTitle(title)
        self.load_data()
        
        if hasattr(self, 'items_table') and self.items_table:
            self.items_table.load_data(self.operation_obj.items)

    def _on_load_error(self, err_msg):
        self.load_worker.deleteLater()
        self.load_thread.deleteLater()
        self.load_worker = None
        self.load_thread = None
        QMessageBox.warning(self, "Load Error", f"Error loading data: {err_msg}")
        self.setEnabled(True)
        title = self.windowTitle().replace(" (Loading...)", "")
        self.setWindowTitle(title)
        self.load_data()
"""
code = code.replace("self.setMinimumSize(600, 500)", "self.setMinimumSize(600, 500)" + on_load)

# 5. Fix _catalog_entity_exists & _validate_stock
old_methods = """    def _catalog_entity_exists(self, item_type, name):
        table = "Products" if item_type == "product" else "Services"
        target = self._normalize_name(name)
        self.database.cursor.execute(
            f"SELECT name FROM {table} WHERE name IS NOT NULL"
        )
        return any(
            self._normalize_name(row[0]) == target
            for row in self.database.cursor.fetchall()
        )

    def _validate_stock(self, items_objects):
        \"\"\"Return a list of error strings for any sale item that exceeds available stock.

        Excludes the current sale's own existing items from the deduction so that editing
        a sale and changing quantities is checked correctly (not double-counted).
        \"\"\"
        errors = []
        current_sale_id = self.operation_id or 0
        cursor = self.database.cursor
        for item in items_objects:
            try:
                product_id = item.get_value('product_id')
                if not product_id:
                    continue
                product_name = item.get_value('product_name') or f"ID {product_id}"
                new_qty = float(item.get_value('quantity') or 0)
                if new_qty <= 0:
                    continue

                cursor.execute(
                    "SELECT COALESCE(SUM(quantity), 0) FROM Import_Items WHERE product_id = %s",
                    (product_id,)
                )
                total_imports = cursor.fetchone()[0] or 0

                # Exclude the current sale so editing doesn't double-count its own items
                cursor.execute(\"\"\"
                    SELECT COALESCE(SUM(si.quantity), 0)
                    FROM Sales_Items si
                    JOIN Sales s ON si.sales_id = s.ID
                    WHERE si.product_id = %s AND (s.is_historical IS NULL OR s.is_historical = FALSE)
                      AND s.state != 'on_hold' AND s.ID != %s
                \"\"\", (product_id, current_sale_id))
                total_sales = cursor.fetchone()[0] or 0

                available = total_imports - total_sales
                if new_qty > available:
                    errors.append(f"{product_name} (Requested: {new_qty}, Available: {available})")
            except Exception as e:
                logger.error(f"Stock validation error for item {item.id}: {e}", exc_info=True)
                pass

        return errors"""

new_methods = """    def _catalog_entity_exists(self, item_type, name):
        target = self._normalize_name(name)
        catalog = getattr(self.database, "sale_catalog", None)
        if catalog:
            entities = catalog.get("products", []) if item_type == "product" else catalog.get("services", [])
            for entity in entities:
                if self._normalize_name(entity.get("name")) == target:
                    return True
            return False
            
        table = "Products" if item_type == "product" else "Services"
        self.database.cursor.execute(
            f"SELECT name FROM {table} WHERE name IS NOT NULL"
        )
        return any(
            self._normalize_name(row[0]) == target
            for row in self.database.cursor.fetchall()
        )

    def _validate_stock(self, items_objects):
        errors = []
        catalog = getattr(self.database, "sale_catalog", None)
        
        if catalog and "products" in catalog:
            products_dict = {p["id"]: p for p in catalog["products"]}
            for item in items_objects:
                try:
                    product_id = item.get_value('product_id')
                    if not product_id:
                        continue
                    new_qty = float(item.get_value('quantity') or 0)
                    if new_qty <= 0:
                        continue
                        
                    product = products_dict.get(int(product_id))
                    if product:
                        stock = float(product.get('stock') or 0)
                        if new_qty > stock:
                            product_name = item.get_value('product_name') or f"ID {product_id}"
                            errors.append(f"{product_name} (Requested: {new_qty}, Available: {stock})")
                except Exception:
                    pass
            return errors
            
        current_sale_id = self.operation_id or 0
        cursor = self.database.cursor
        for item in items_objects:
            try:
                product_id = item.get_value('product_id')
                if not product_id:
                    continue
                product_name = item.get_value('product_name') or f"ID {product_id}"
                new_qty = float(item.get_value('quantity') or 0)
                if new_qty <= 0:
                    continue

                cursor.execute(
                    "SELECT COALESCE(SUM(quantity), 0) FROM Import_Items WHERE product_id = %s",
                    (product_id,)
                )
                total_imports = cursor.fetchone()[0] or 0

                cursor.execute(\"\"\"
                    SELECT COALESCE(SUM(si.quantity), 0)
                    FROM Sales_Items si
                    JOIN Sales s ON si.sales_id = s.ID
                    WHERE si.product_id = %s AND (s.is_historical IS NULL OR s.is_historical = FALSE)
                      AND s.state != 'on_hold' AND s.ID != %s
                \"\"\", (product_id, current_sale_id))
                total_sales = cursor.fetchone()[0] or 0

                available = total_imports - total_sales
                if new_qty > available:
                    errors.append(f"{product_name} (Requested: {new_qty}, Available: {available})")
            except Exception as e:
                logger.error(f"Stock validation error for item {item.id}: {e}", exc_info=True)
                pass

        return errors"""

code = code.replace(old_methods, new_methods)

# 6. Fix _save_changes_impl
old_save = """                action = "updated" if self.operation_id else "created"
                result = self._save_sale_atomically()
                self.operation_id = result['sale_id']
                self.operation_obj.id = result['sale_id']
                self.operation_obj.set_value('id', result['sale_id'])
                expected = result.get('expected', 0)
                saved = result.get('saved', 0)
                if saved != expected:
                    raise RuntimeError(
                        f"Sale was not saved: {expected} visible items were found, "
                        f"but the server confirmed {saved} saved items."
                    )
                QMessageBox.information(
                    self, "Success",
                    f"Operation {action} successfully. {saved} items saved.\\n"
                    f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                    f"deleted: {result.get('deleted', 0)}."
                )
                self.accept()
            else:
                items_objects = self.items_table.get_items_data()
                action = "updated" if self.operation_id else "created"
                result = self._save_import_atomically()
                self.operation_id = result['import_id']
                self.operation_obj.id = result['import_id']
                self.operation_obj.set_value('id', result['import_id'])
                expected = result.get('expected', 0)
                saved = result.get('saved', 0)
                if saved != expected:
                    raise RuntimeError(
                        f"Import was not saved: {expected} visible items were found, "
                        f"but the server confirmed {saved} saved items."
                    )
                QMessageBox.information(
                    self, "Success",
                    f"Operation {action} successfully. {saved} items saved.\\n"
                    f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
                    f"deleted: {result.get('deleted', 0)}."
                )
                self.accept()

        except Exception as e:
            logger.error(f"Error saving operation: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to save operation: {str(e)}")"""

new_save = """                action = "updated" if self.operation_id else "created"
                
                self._saving = True
                self.setEnabled(False)
                self.setWindowTitle(self.windowTitle() + " (Saving...)")
                
                self.save_thread = QThread()
                self.save_worker = SaveWorker(self, is_import=False)
                self.save_worker.moveToThread(self.save_thread)
                self.save_thread.started.connect(self.save_worker.process)
                self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
                self.save_worker.error.connect(self._on_save_error)
                self.save_worker.finished.connect(self.save_thread.quit)
                self.save_worker.error.connect(self.save_thread.quit)
                self.save_thread.start()
                return # Dialog accepted in _on_save_finished
            else:
                items_objects = self.items_table.get_items_data()
                action = "updated" if self.operation_id else "created"
                
                self._saving = True
                self.setEnabled(False)
                self.setWindowTitle(self.windowTitle() + " (Saving...)")
                
                self.save_thread = QThread()
                self.save_worker = SaveWorker(self, is_import=True)
                self.save_worker.moveToThread(self.save_thread)
                self.save_thread.started.connect(self.save_worker.process)
                self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
                self.save_worker.error.connect(self._on_save_error)
                self.save_worker.finished.connect(self.save_thread.quit)
                self.save_worker.error.connect(self.save_thread.quit)
                self.save_thread.start()
                return # Dialog accepted in _on_save_finished

        except Exception as e:
            logger.error(f"Error saving operation: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to save operation: {str(e)}")

    def _on_save_finished(self, result, action):
        self._saving = False
        self.setEnabled(True)
        title = self.windowTitle().replace(" (Saving...)", "")
        self.setWindowTitle(title)
        
        if hasattr(self, 'save_worker') and self.save_worker:
            self.save_worker.deleteLater()
            self.save_worker = None
        if hasattr(self, 'save_thread') and self.save_thread:
            self.save_thread.deleteLater()
            self.save_thread = None

        if self.operation_obj.section == 'Sales':
            self.operation_id = result['sale_id']
            self.operation_obj.id = result['sale_id']
            self.operation_obj.set_value('id', result['sale_id'])
        else:
            self.operation_id = result['import_id']
            self.operation_obj.id = result['import_id']
            self.operation_obj.set_value('id', result['import_id'])
            
        expected = result.get('expected', 0)
        saved = result.get('saved', 0)
        if saved != expected:
            QMessageBox.critical(
                self, "Save Error",
                f"Operation was not saved correctly: {expected} visible items were found, "
                f"but the server confirmed {saved} saved items."
            )
            return

        QMessageBox.information(
            self, "Success",
            f"Operation {action} successfully. {saved} items saved.\\n"
            f"Inserted: {result.get('inserted', 0)}, updated: {result.get('updated', 0)}, "
            f"deleted: {result.get('deleted', 0)}."
        )
        self.accept()

    def _on_save_error(self, err_msg):
        self._saving = False
        self.setEnabled(True)
        title = self.windowTitle().replace(" (Saving...)", "")
        self.setWindowTitle(title)
        
        if hasattr(self, 'save_worker') and self.save_worker:
            self.save_worker.deleteLater()
            self.save_worker = None
        if hasattr(self, 'save_thread') and self.save_thread:
            self.save_thread.deleteLater()
            self.save_thread = None
            
        QMessageBox.critical(self, "Error", f"Failed to save operation:\\n{err_msg}")
"""

code = code.replace(old_save, new_save)

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(code)
