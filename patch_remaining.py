import os

def insert_shiboken(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    if not any("import shiboken6" in line for line in lines):
        for i, line in enumerate(lines):
            if "from PySide6" in line or "import logging" in line:
                lines.insert(i, "import shiboken6\n")
                break
                
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(lines)

def patch_file(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
        
    for old, new in replacements:
        if old in code:
            code = code.replace(old, new)
        else:
            print(f"Warning: Could not find block in {filepath}")
            print("--- Expected:")
            print(old)
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)


# 1. home_tab.py
insert_shiboken("ui/tabs/home_tab.py")

home_replacements = [
(
"""    def _start_remote_dashboard_refresh(self):
        existing_thread = getattr(self, "_dashboard_thread", None)
        if existing_thread is not None and existing_thread.isRunning():
            logger.warning("Duplicate dashboard refresh requested while active. Ignoring.")
            return False""",
"""    def _start_remote_dashboard_refresh(self):
        existing_thread = getattr(self, "_dashboard_thread", None)
        is_running = False
        if existing_thread is not None:
            try:
                if shiboken6.isValid(existing_thread) and existing_thread.isRunning():
                    is_running = True
            except RuntimeError:
                pass
        
        if is_running:
            logger.warning("Duplicate dashboard refresh requested while active. Ignoring.")
            return False"""
),
(
"""        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_dashboard_thread_finished)""",
"""        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._on_dashboard_thread_finished(t, w))"""
),
(
"""    def _on_dashboard_thread_finished(self):
        thread = getattr(self, "_dashboard_thread", None)
        if thread is not None and not thread.isRunning():
            self._dashboard_thread = None
            self._dashboard_worker = None""",
"""    def _on_dashboard_thread_finished(self, expected_thread=None, expected_worker=None):
        if getattr(self, "_dashboard_thread", None) is expected_thread:
            self._dashboard_thread = None
        if getattr(self, "_dashboard_worker", None) is expected_worker:
            self._dashboard_worker = None"""
),
(
"""    def _wait_for_dashboard_thread(self, timeout_ms=5000):
        thread = getattr(self, "_dashboard_thread", None)
        if thread is None or not thread.isRunning():
            return True
            
        if thread == QThread.currentThread():
            return False
            
        thread.requestInterruption()
        thread.quit()
        
        if not thread.wait(timeout_ms):
            logger.error("Dashboard thread did not stop in time.")
            return False
            
        return True""",
"""    def _wait_for_dashboard_thread(self, timeout_ms=5000):
        thread = getattr(self, "_dashboard_thread", None)
        if thread is None:
            return True
            
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._dashboard_thread = None
                self._dashboard_worker = None
                return True
                
            if thread == QThread.currentThread():
                return False
                
            thread.requestInterruption()
            thread.quit()
            
            if not thread.wait(timeout_ms):
                logger.error("Dashboard thread did not stop in time.")
                return False
                
            self._dashboard_thread = None
            self._dashboard_worker = None
            return True
        except RuntimeError:
            self._dashboard_thread = None
            self._dashboard_worker = None
            return True"""
)
]

patch_file("ui/tabs/home_tab.py", home_replacements)


# 2. reports_dialog.py
insert_shiboken("ui/dialogs/reports_dialog.py")

reports_replacements = [
(
"""    def _generate_report(self):
        existing_thread = getattr(self, "_report_thread", None)
        if existing_thread is not None and existing_thread.isRunning():
            QMessageBox.warning(self, "Working", "A report is already being generated.")
            return""",
"""    def _generate_report(self):
        existing_thread = getattr(self, "_report_thread", None)
        is_running = False
        if existing_thread is not None:
            try:
                if shiboken6.isValid(existing_thread) and existing_thread.isRunning():
                    is_running = True
            except RuntimeError:
                pass
                
        if is_running:
            QMessageBox.warning(self, "Working", "A report is already being generated.")
            return"""
),
(
"""        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_report_thread_finished)""",
"""        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._on_report_thread_finished(t, w))"""
),
(
"""    def _on_report_thread_finished(self):
        thread = getattr(self, "_report_thread", None)
        if thread and thread.isRunning():
            return
            
        self._report_thread = None
        self._report_worker = None""",
"""    def _on_report_thread_finished(self, expected_thread=None, expected_worker=None):
        if getattr(self, "_report_thread", None) is expected_thread:
            self._report_thread = None
        if getattr(self, "_report_worker", None) is expected_worker:
            self._report_worker = None"""
),
(
"""    def _wait_for_report_thread(self, timeout_ms=5000):
        thread = getattr(self, "_report_thread", None)
        if thread is None or not thread.isRunning():
            return True
            
        if thread == QThread.currentThread():
            return False
            
        thread.requestInterruption()
        thread.quit()
        
        if not thread.wait(timeout_ms):
            return False
            
        return True""",
"""    def _wait_for_report_thread(self, timeout_ms=5000):
        thread = getattr(self, "_report_thread", None)
        if thread is None:
            return True
            
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._report_thread = None
                self._report_worker = None
                return True
                
            if thread == QThread.currentThread():
                return False
                
            thread.requestInterruption()
            thread.quit()
            
            if not thread.wait(timeout_ms):
                return False
                
            self._report_thread = None
            self._report_worker = None
            return True
        except RuntimeError:
            self._report_thread = None
            self._report_worker = None
            return True"""
)
]

patch_file("ui/dialogs/reports_dialog.py", reports_replacements)


# 3. backups_dialog.py
insert_shiboken("ui/dialogs/backups_dialog.py")

backups_replacements = [
(
"""    def _wait_for_worker_thread(self, timeout_ms=5000):
        thread = getattr(self, "_worker_thread", None)
        if thread is None or not thread.isRunning():
            return True
            
        if thread == QThread.currentThread():
            return False
            
        thread.requestInterruption()
        thread.quit()
        
        if not thread.wait(timeout_ms):
            return False
            
        return True""",
"""    def _wait_for_worker_thread(self, timeout_ms=5000):
        thread = getattr(self, "_worker_thread", None)
        if thread is None:
            return True
            
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._worker_thread = None
                self._worker = None
                return True
                
            if thread == QThread.currentThread():
                return False
                
            thread.requestInterruption()
            thread.quit()
            
            if not thread.wait(timeout_ms):
                return False
                
            self._worker_thread = None
            self._worker = None
            return True
        except RuntimeError:
            self._worker_thread = None
            self._worker = None
            return True"""
),
(
"""    def _on_worker_thread_finished(self):
        thread = getattr(self, "_worker_thread", None)
        if thread and thread.isRunning():
            return
            
        self._worker_thread = None
        self._worker = None""",
"""    def _on_worker_thread_finished(self, expected_thread=None, expected_worker=None):
        if getattr(self, "_worker_thread", None) is expected_thread:
            self._worker_thread = None
        if getattr(self, "_worker", None) is expected_worker:
            self._worker = None"""
),
(
"""        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)""",
"""        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._on_worker_thread_finished(t, w))"""
)
]

# Note: backups_dialog might have multiple workers (e.g. download, restore, create). I need to check how they are spawned.
patch_file("ui/dialogs/backups_dialog.py", backups_replacements)

print("Patching done!")
