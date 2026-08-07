import shiboken6
from PySide6.QtCore import QThread

def is_valid_qobject(obj):
    """Safely check if a PySide6 QObject wrapper points to a valid C++ object."""
    if obj is None:
        return False
    try:
        return shiboken6.isValid(obj)
    except Exception:
        return False

with open("ui/tabs/base_tab.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# Add import shiboken6 if not there
has_shiboken = any("import shiboken6" in line for line in lines)
if not has_shiboken:
    # insert after import PySide6 or logging
    for i, line in enumerate(lines):
        if "from PySide6" in line:
            lines.insert(i, "import shiboken6\n")
            break

code = "".join(lines)

old_start_refresh = """        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_refresh_thread_finished)
        thread.finished.connect(
            lambda: diagnostics.worker_cleanup("table_fetch", self.section, refresh_id)
        )"""

new_start_refresh = """        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda t=thread, w=worker: self._on_refresh_thread_finished(t, w)
        )
        thread.finished.connect(
            lambda: diagnostics.worker_cleanup("table_fetch", self.section, refresh_id)
        )"""

code = code.replace(old_start_refresh, new_start_refresh)

old_on_refresh_thread_finished = """    def _on_refresh_thread_finished(self):
        thread = getattr(self, "_refresh_thread", None)
        if thread is not None and not thread.isRunning():
            self._refresh_thread = None
            self._refresh_worker = None"""

new_on_refresh_thread_finished = """    def _on_refresh_thread_finished(self, expected_thread=None, expected_worker=None):
        if getattr(self, "_refresh_thread", None) is expected_thread:
            self._refresh_thread = None
        if getattr(self, "_refresh_worker", None) is expected_worker:
            self._refresh_worker = None"""

code = code.replace(old_on_refresh_thread_finished, new_on_refresh_thread_finished)

old_start_refresh_beginning = """    def _start_refresh(self, fetcher, refresh_id, worker_db=None, mode='local'):
        existing_thread = getattr(self, "_refresh_thread", None)
        if existing_thread is not None and existing_thread.isRunning():
            logger.warning("Duplicate refresh requested while thread is active. Ignoring.")
            if worker_db is not None:
                worker_db.close()
            return"""

new_start_refresh_beginning = """    def _start_refresh(self, fetcher, refresh_id, worker_db=None, mode='local'):
        existing_thread = getattr(self, "_refresh_thread", None)
        is_running = False
        if existing_thread is not None:
            try:
                if shiboken6.isValid(existing_thread) and existing_thread.isRunning():
                    is_running = True
            except RuntimeError:
                pass
                
        if is_running:
            logger.warning("Duplicate refresh requested while thread is active. Ignoring.")
            if worker_db is not None:
                worker_db.close()
            return"""

code = code.replace(old_start_refresh_beginning, new_start_refresh_beginning)

old_wait = """    def _wait_for_refresh_thread(self, timeout_ms=5000):
        \"\"\"Do not destroy a QThread while an in-flight HTTP call is unwinding.\"\"\"
        self._cache.clear()
        thread = getattr(self, "_refresh_thread", None)
        if thread is None or not thread.isRunning():
            return True
            
        if thread == QThread.currentThread():
            return False
            
        thread.requestInterruption()
        thread.quit()
        
        if not thread.wait(timeout_ms):
            logger.error(
                "Remote refresh thread did not stop section=%s timeout=%sms", 
                self.section, timeout_ms
            )
            return False
            
        return True"""

new_wait = """    def _wait_for_refresh_thread(self, timeout_ms=5000):
        \"\"\"Do not destroy a QThread while an in-flight HTTP call is unwinding.\"\"\"
        self._cache.clear()
        thread = getattr(self, "_refresh_thread", None)
        
        if thread is None:
            return True
            
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._refresh_thread = None
                self._refresh_worker = None
                return True
                
            if thread == QThread.currentThread():
                return False
                
            thread.requestInterruption()
            thread.quit()
            
            if not thread.wait(timeout_ms):
                logger.error(
                    "Remote refresh thread did not stop section=%s timeout=%sms", 
                    self.section, timeout_ms
                )
                return False
                
            self._refresh_thread = None
            self._refresh_worker = None
            return True
            
        except RuntimeError:
            # If it's deleted during the checks, it's already finished.
            self._refresh_thread = None
            self._refresh_worker = None
            return True"""

code = code.replace(old_wait, new_wait)

with open("ui/tabs/base_tab.py", "w", encoding="utf-8") as f:
    f.write(code)

print("Patched base_tab.py successfully.")
