import re

def safe_replace(filepath, pattern, replacement):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched {count} instances in {filepath}")

# 1. replace `if thread is None or not thread.isRunning():` in _wait_for_*
wait_pattern = r"(\s*)if\s+(existing_thread|thread)\s+is\s+None\s+or\s+not\s+(existing_thread|thread)\.isRunning\(\):"
wait_replacement = r"""\1if \2 is None:
\1    return True
\1try:
\1    if not shiboken6.isValid(\2) or not \2.isRunning():
\1        return True
\1except RuntimeError:
\1    return True"""

safe_replace("ui/tabs/home_tab.py", wait_pattern, wait_replacement)
safe_replace("ui/dialogs/reports_dialog.py", wait_pattern, wait_replacement)
safe_replace("ui/dialogs/backups_dialog.py", wait_pattern, wait_replacement)
safe_replace("ui/tabs/base_tab.py", wait_pattern, wait_replacement)

# 2. replace duplicate active checks: `if existing_thread is not None and existing_thread.isRunning():`
active_pattern = r"(\s*)if\s+(existing_thread|thread)\s+is\s+not\s+None\s+and\s+(existing_thread|thread)\.isRunning\(\):"
active_replacement = r"""\1is_running = False
\1if \2 is not None:
\1    try:
\1        if shiboken6.isValid(\2) and \2.isRunning():
\1            is_running = True
\1    except RuntimeError:
\1        pass
\1if is_running:"""

safe_replace("ui/tabs/home_tab.py", active_pattern, active_replacement)
safe_replace("ui/dialogs/reports_dialog.py", active_pattern, active_replacement)
safe_replace("ui/dialogs/backups_dialog.py", active_pattern, active_replacement)
safe_replace("ui/tabs/base_tab.py", active_pattern, active_replacement)

# 3. replace `_on_..._finished` where it has `isRunning()` check
finished_pattern = r"(\s*)if\s+thread\s+is\s+not\s+None\s+and\s+not\s+thread\.isRunning\(\):\s+self\._(\w+)_thread\s*=\s*None\s+self\._(\w+)_worker\s*=\s*None"
finished_replacement = r"""\1try:
\1    if thread is not None and shiboken6.isValid(thread) and not thread.isRunning():
\1        self._\2_thread = None
\1        self._\3_worker = None
\1except RuntimeError:
\1    self._\2_thread = None
\1    self._\3_worker = None"""

safe_replace("ui/tabs/home_tab.py", finished_pattern, finished_replacement)
safe_replace("ui/tabs/base_tab.py", finished_pattern, finished_replacement)

# 4. reports/backups have:
# if thread and thread.isRunning(): return
# self._report_thread = None
alt_finished_pattern = r"(\s*)if\s+thread\s+and\s+thread\.isRunning\(\):\s+return\s+self\._(\w+)_thread\s*=\s*None\s+self\._(\w+)_worker\s*=\s*None"
alt_finished_replacement = r"""\1try:
\1    if thread and shiboken6.isValid(thread) and thread.isRunning():
\1        return
\1except RuntimeError:
\1    pass
\1self._\2_thread = None
\1self._\3_worker = None"""
safe_replace("ui/dialogs/reports_dialog.py", alt_finished_pattern, alt_finished_replacement)
safe_replace("ui/dialogs/backups_dialog.py", alt_finished_pattern, alt_finished_replacement)

