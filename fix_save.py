import re

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    content = f.read()

# Replace SaveWorker
old_worker = """class SaveWorker(QObject):
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
            self.error.emit(str(e))"""

new_worker = """class SaveWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, database, is_import, save_kwargs):
        super().__init__()
        self.database = database
        self.is_import = is_import
        self.save_kwargs = save_kwargs
        
    @Slot()
    def process(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            if self.is_import:
                res = self.database.save_import_with_items(**self.save_kwargs)
                if not isinstance(res, dict) or res.get("transaction") != "committed":
                    raise RuntimeError(f"Host returned an invalid import-save result: {res!r}")
                res['expected'] = len(self.save_kwargs.get('items', []))
            else:
                res = self.database.save_sale_with_items(**self.save_kwargs)
                if not isinstance(res, dict) or res.get('transaction') != 'committed':
                    raise RuntimeError(f"Host returned an invalid sale-save result: {res!r}")
                res['expected'] = len(self.save_kwargs.get('items', []))
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))"""

content = content.replace(old_worker, new_worker)

# Replace the save block in _save_changes_impl
old_impl = """            # Save operation to database first (ensures ID exists)
            if self.operation_obj.section in ('Sales', 'Imports'):
                is_import = (self.operation_obj.section == 'Imports')
                
                if not is_import:
                    items_objects = self.items_table.get_items_data()
                    is_historical = bool(self.operation_obj.get_value('is_historical'))
                    sale_state = self.operation_obj.get_value('state') or 'pending'
                    if not is_historical and sale_state != 'on_hold':
                        stock_errors = self._validate_stock(items_objects)
                        mw = self._get_main_window()
                        warn_stock = getattr(mw, 'warn_insufficient_stock', True) if mw else True
                        if stock_errors and warn_stock:
                            reply = QMessageBox.warning(
                                self, "Insufficient Stock",
                                "Not enough stock for:\\n\\n" +
                                "\\n".join(f"  • {e}" for e in stock_errors) +
                                "\\n\\nSave anyway?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No
                            )
                            if reply != QMessageBox.StandardButton.Yes:
                                return
                    if not self._confirm_sale_summary():
                        return
                        
                action = "updated" if self.operation_id else "created"
                
                self.save_thread = QThread()
                self.save_worker = SaveWorker(self, is_import)
                self.save_worker.moveToThread(self.save_thread)
                self.save_thread.started.connect(self.save_worker.process)
                self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
                self.save_worker.error.connect(self._on_save_error)
                self.save_thread.start()
                return"""

new_impl = """            # Save operation to database first (ensures ID exists)
            if self.operation_obj.section in ('Sales', 'Imports'):
                is_import = (self.operation_obj.section == 'Imports')
                
                if not is_import:
                    items_objects = self.items_table.get_items_data()
                    is_historical = bool(self.operation_obj.get_value('is_historical'))
                    sale_state = self.operation_obj.get_value('state') or 'pending'
                    if not is_historical and sale_state != 'on_hold':
                        stock_errors = self._validate_stock(items_objects)
                        mw = self._get_main_window()
                        warn_stock = getattr(mw, 'warn_insufficient_stock', True) if mw else True
                        if stock_errors and warn_stock:
                            reply = QMessageBox.warning(
                                self, "Insufficient Stock",
                                "Not enough stock for:\\n\\n" +
                                "\\n".join(f"  • {e}" for e in stock_errors) +
                                "\\n\\nSave anyway?",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No
                            )
                            if reply != QMessageBox.StandardButton.Yes:
                                return
                    if not self._confirm_sale_summary():
                        return
                        
                # BUILD PAYLOAD ON GUI THREAD
                raw_items = self.items_table.get_current_table_data()
                prepared = []
                if is_import:
                    for raw in raw_items:
                        item = dict(raw)
                        item.pop("row_index", None)
                        prepared.append(item)
                else:
                    for index, raw in enumerate(raw_items, start=1):
                        item = dict(raw)
                        item.pop('row_index', None)
                        product_id = item.get('product_id')
                        service_id = item.get('service_id')
                        item['product_id'] = product_id
                        item['service_id'] = service_id
                        item['item_type'] = str(
                            item.get('item_type')
                            or ('product' if product_id else ('service' if service_id else ''))
                        ).casefold()
                        item['is_new'] = not bool(item.get('id'))
                        prepared.append(item)

                header = {
                    key: self.operation_obj.get_value(key)
                    for key in self.operation_obj.get_visible_parameters('database')
                    if not self.operation_obj.is_parameter_calculated(key)
                }
                header["operation_token"] = (
                    self.operation_obj.get_value("operation_token") or self.operation_token
                )
                
                save_kwargs = {}
                if is_import:
                    save_kwargs = {
                        'import_data': header,
                        'items': prepared,
                        'import_id': self.operation_id,
                        'visible_row_count': len(raw_items)
                    }
                else:
                    header["is_historical"] = bool(self.operation_obj.get_value("is_historical"))
                    save_kwargs = {
                        'sale_data': header,
                        'items': prepared,
                        'sale_id': self.operation_id,
                        'visible_row_count': len(raw_items),
                        'pending_entities': getattr(self, 'pending_entities', [])
                    }

                action = "updated" if self.operation_id else "created"
                
                self.save_thread = QThread()
                self.save_worker = SaveWorker(self.database, is_import, save_kwargs)
                self.save_worker.moveToThread(self.save_thread)
                self.save_thread.started.connect(self.save_worker.process)
                self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
                self.save_worker.error.connect(self._on_save_error)
                self.save_thread.start()
                return"""

content = content.replace(old_impl, new_impl)

# Remove old _save_sale_atomically and _save_import_atomically
content = re.sub(r'    def _save_sale_atomically\(self\):.*?return result\n\n    def _save_import_atomically\(self\):.*?return result\n\n', '', content, flags=re.DOTALL)

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(content)
