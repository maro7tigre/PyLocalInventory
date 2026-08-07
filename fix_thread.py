with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "r", encoding="utf-8") as f:
    code = f.read()

old_block = """                self.save_thread = QThread()
                self.save_worker = SaveWorker(self.database, is_import, save_kwargs)
                self.save_worker.moveToThread(self.save_thread)
                self.save_thread.started.connect(self.save_worker.process)
                self.save_worker.finished.connect(lambda res, act=action: self._on_save_finished(res, act))
                self.save_worker.error.connect(self._on_save_error)
                self.save_thread.start()"""

new_block = """                self.save_thread = QThread()
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

if old_block in code:
    code = code.replace(old_block, new_block)
    print("Replaced thread start block!")
else:
    print("Failed to replace thread start block")

with open("ui/dialogs/edit_dialogs/base_operation_dialog.py", "w", encoding="utf-8") as f:
    f.write(code)
