with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    code = f.read()

old_load_block = """        self.load_worker.moveToThread(self.load_thread)
        self.load_thread.started.connect(self.load_worker.process)
        self.load_worker.finished.connect(self._on_load_finished)
        self.load_worker.error.connect(self._on_load_error)
        self.load_worker.finished.connect(self.load_thread.quit)
        self.load_worker.error.connect(self.load_thread.quit)
        self.load_thread.start()"""

new_load_block = """        self.load_worker.moveToThread(self.load_thread)
        self.load_thread.started.connect(self.load_worker.process)
        
        # Safe thread cleanup lifecycle
        self.load_worker.finished.connect(self.load_thread.quit)
        self.load_worker.finished.connect(self.load_worker.deleteLater)
        self.load_thread.finished.connect(self.load_thread.deleteLater)
        self.load_worker.error.connect(self.load_thread.quit)
        self.load_worker.error.connect(self.load_worker.deleteLater)
        
        # Business logic callbacks
        self.load_worker.finished.connect(self._on_load_finished)
        self.load_worker.error.connect(self._on_load_error)
        
        self.load_thread.start()"""

if old_load_block in code:
    code = code.replace(old_load_block, new_load_block)
    print("Replaced load thread start block!")
else:
    print("Failed to replace load thread start block")

old_on_load_finished = """    def _on_load_finished(self):
        if hasattr(self, 'load_worker') and self.load_worker:
            self.load_worker.deleteLater()
            self.load_worker = None
        if hasattr(self, 'load_thread') and self.load_thread:
            self.load_thread.deleteLater()
            self.load_thread = None"""

new_on_load_finished = """    def _on_load_finished(self):
        # Thread cleanup is handled safely by QThread.finished -> deleteLater
        self.load_worker = None
        self.load_thread = None"""

if old_on_load_finished in code:
    code = code.replace(old_on_load_finished, new_on_load_finished)
    print("Replaced _on_load_finished cleanup!")
else:
    print("Failed to replace _on_load_finished cleanup!")

old_on_load_error = """    def _on_load_error(self, err_msg):
        if hasattr(self, 'load_worker') and self.load_worker:
            self.load_worker.deleteLater()
            self.load_worker = None
        if hasattr(self, 'load_thread') and self.load_thread:
            self.load_thread.deleteLater()
            self.load_thread = None"""

new_on_load_error = """    def _on_load_error(self, err_msg):
        self.load_worker = None
        self.load_thread = None"""

if old_on_load_error in code:
    code = code.replace(old_on_load_error, new_on_load_error)
    print("Replaced _on_load_error cleanup!")
else:
    print("Failed to replace _on_load_error cleanup!")


with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(code)
