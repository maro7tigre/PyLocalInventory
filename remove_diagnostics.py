import re
import sys

def safe_replace(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    for old, new in replacements:
        # Use regex to match the old block more flexibly due to time string formatting differences
        code = re.sub(re.escape(old).replace(r'\{time\.time\(\)\:\.3f\}', r'.*?'), new, code, flags=re.DOTALL)
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

replacements = [
(
"""    def save_changes(self):
        import time, threading, traceback, sys
        print(f"[{time.time():.3f}] [MainThread] SAVE_CLICK")
        
        def dump_threads():
            time.sleep(2)
            print(f"\\n[{time.time():.3f}] [DumperThread] DUMPING ALL THREAD STACKS")
            for th in threading.enumerate():
                print(f"\\n--- Thread: {th.name} (ident={th.ident}) ---")
                frame = sys._current_frames().get(th.ident)
                if frame:
                    traceback.print_stack(frame)
                else:
                    print("No frame found.")
            print("DUMP COMPLETE\\n")
            
        threading.Thread(target=dump_threads, name="DiagnosticDumper", daemon=True).start()

        if self._saving:
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        try:
            print(f"[{time.time():.3f}] [MainThread] _save_changes_impl START")
            self._save_changes_impl()
            print(f"[{time.time():.3f}] [MainThread] _save_changes_impl END")
        except Exception as e:
            print(f"[{time.time():.3f}] [MainThread] ERROR IN _save_changes_impl: {e}")
            raise
        finally:
            if self.result() == QDialog.Rejected and not (hasattr(self, 'save_thread') and self.save_thread):
                self._saving = False
                if getattr(self, 'save_btn', None):
                    self.save_btn.setEnabled(True)
                    self.save_btn.setText("Save")""",
"""    def save_changes(self):
        \"\"\"Prevent double-clicks from starting the same transaction twice.\"\"\"
        if self._saving:
            return
        self._saving = True
        self.save_btn.setEnabled(False)
        self.save_btn.setText("Saving...")
        try:
            self._save_changes_impl()
        finally:
            if self.result() == QDialog.Rejected and not (hasattr(self, 'save_thread') and self.save_thread):
                self._saving = False
                if getattr(self, 'save_btn', None):
                    self.save_btn.setEnabled(True)
                    self.save_btn.setText("Save")"""
)
]

safe_replace("ui/dialogs/edit_dialogs/base_operation_dialog.py", replacements)
print("Diagnostics removed")
