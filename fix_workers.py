import re

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Update SaveWorker and LoadWorker
old_workers = """class SaveWorker(QObject):
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
            self.error.emit(str(e))

class LoadWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self, operation_obj, database, fetch_catalog):
        super().__init__()
        self.operation_obj = operation_obj
        self.database = database
        self.fetch_catalog = fetch_catalog

    @Slot()
    def process(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            if self.operation_obj:
                self.operation_obj.load_database_data()
            if self.fetch_catalog and getattr(self.database, 'get_sale_catalog', None):
                self.database.sale_catalog = self.database.get_sale_catalog()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))"""

new_workers = """class SaveWorker(QObject):
    finished = Signal(object)
    error = Signal(str)
    
    def __init__(self, database, is_import, save_kwargs):
        super().__init__()
        self.database = database
        self.is_import = is_import
        self.save_kwargs = save_kwargs
        
    @Slot()
    def process(self):
        worker_db = self.database
        is_local = hasattr(self.database, 'profile_manager') and hasattr(self.database, 'conn')
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
                
            if is_local:
                from core.database import Database
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, 'language', 'en')
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect():
                    raise RuntimeError(f"Worker could not connect to database: {worker_db.last_error}")

            if self.is_import:
                res = worker_db.save_import_with_items(**self.save_kwargs)
                if not isinstance(res, dict) or res.get("transaction") != "committed":
                    raise RuntimeError(f"Host returned an invalid import-save result: {res!r}")
                res['expected'] = len(self.save_kwargs.get('items', []))
            else:
                res = worker_db.save_sale_with_items(**self.save_kwargs)
                if not isinstance(res, dict) or res.get('transaction') != 'committed':
                    raise RuntimeError(f"Host returned an invalid sale-save result: {res!r}")
                res['expected'] = len(self.save_kwargs.get('items', []))
            self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if is_local and worker_db and worker_db != self.database:
                worker_db.close()

class LoadWorker(QObject):
    finished = Signal()
    error = Signal(str)

    def __init__(self, operation_obj, database, fetch_catalog):
        super().__init__()
        self.operation_obj = operation_obj
        self.database = database
        self.fetch_catalog = fetch_catalog

    @Slot()
    def process(self):
        worker_db = self.database
        is_local = hasattr(self.database, 'profile_manager') and hasattr(self.database, 'conn')
        old_db = getattr(self.operation_obj, 'database', None) if self.operation_obj else None
        
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
                
            if is_local:
                from core.database import Database
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, 'language', 'en')
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect():
                    raise RuntimeError(f"Worker could not connect to database: {worker_db.last_error}")

            if self.operation_obj:
                self.operation_obj.database = worker_db
                self.operation_obj.load_database_data()
                
            if self.fetch_catalog and getattr(worker_db, 'get_sale_catalog', None):
                self.database.sale_catalog = worker_db.get_sale_catalog()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self.operation_obj:
                self.operation_obj.database = old_db
            if is_local and worker_db and worker_db != self.database:
                worker_db.close()"""

if old_workers in code:
    code = code.replace(old_workers, new_workers)
    print("Replaced Workers!")
else:
    print("WARNING: Could not find old workers block!")


# 2. Fix _on_save_finished and _on_save_error to remove manual deleteLater
old_on_save_finished = """    def _on_save_finished(self, result, action):
        if hasattr(self, 'save_worker') and self.save_worker:
            self.save_worker.deleteLater()
            self.save_worker = None
        if hasattr(self, 'save_thread') and self.save_thread:
            self.save_thread.deleteLater()
            self.save_thread = None"""

new_on_save_finished = """    def _on_save_finished(self, result, action):
        # Thread cleanup is handled safely by QThread.finished -> deleteLater
        self.save_worker = None
        self.save_thread = None"""

if old_on_save_finished in code:
    code = code.replace(old_on_save_finished, new_on_save_finished)
    print("Replaced _on_save_finished cleanup!")
else:
    print("WARNING: Could not find old _on_save_finished block!")
    
old_on_save_error = """    def _on_save_error(self, err_msg):
        if hasattr(self, 'save_worker') and self.save_worker:
            self.save_worker.deleteLater()
            self.save_worker = None
        if hasattr(self, 'save_thread') and self.save_thread:
            self.save_thread.deleteLater()
            self.save_thread = None"""
            
new_on_save_error = """    def _on_save_error(self, err_msg):
        self.save_worker = None
        self.save_thread = None"""

if old_on_save_error in code:
    code = code.replace(old_on_save_error, new_on_save_error)
    print("Replaced _on_save_error cleanup!")
else:
    print("WARNING: Could not find old _on_save_error block!")

# 3. Fix thread lifecycle connections
old_thread_start = """            self.save_thread = QThread()
            self.save_worker = SaveWorker(self.database, is_import, save_kwargs)
            self.save_worker.moveToThread(self.save_thread)
            self.save_thread.started.connect(self.save_worker.process)
            self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
            self.save_worker.error.connect(self._on_save_error)
            self.save_thread.start()"""
            
new_thread_start = """            self.save_thread = QThread()
            self.save_worker = SaveWorker(self.database, is_import, save_kwargs)
            self.save_worker.moveToThread(self.save_thread)
            self.save_thread.started.connect(self.save_worker.process)
            
            # Safe thread cleanup lifecycle
            self.save_worker.finished.connect(self.save_thread.quit)
            self.save_worker.finished.connect(self.save_worker.deleteLater)
            self.save_thread.finished.connect(self.save_thread.deleteLater)
            self.save_worker.error.connect(self.save_thread.quit)
            self.save_worker.error.connect(self.save_worker.deleteLater)
            
            # Business logic callbacks
            self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
            self.save_worker.error.connect(self._on_save_error)
            
            self.save_thread.start()"""

if old_thread_start in code:
    code = code.replace(old_thread_start, new_thread_start)
    print("Replaced thread start block!")
else:
    print("WARNING: Could not find old thread start block!")

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(code)
