import re

def safe_replace(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    for old, new in replacements:
        if old in code:
            code = code.replace(old, new)
        else:
            print(f"Warning: Could not find block in {filepath}")
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

# 1. base_operation_dialog.py
replacements_base_op = [
(
"import uuid\n",
"import uuid\nimport shiboken6\n\n_active_background_threads = set()\n"
),
(
"""        self.load_thread.start()""",
"""        _active_background_threads.add(self.load_thread)
        self.load_thread.finished.connect(lambda t=self.load_thread: _active_background_threads.discard(t))
        self.load_thread.start()"""
),
(
"""                self.save_thread.start()""",
"""                _active_background_threads.add(self.save_thread)
                self.save_thread.finished.connect(lambda t=self.save_thread: _active_background_threads.discard(t))
                self.save_thread.start()"""
)
]

safe_replace("ui/dialogs/edit_dialogs/base_operation_dialog.py", replacements_base_op)
print("Added global thread roots to base_operation_dialog.py")
