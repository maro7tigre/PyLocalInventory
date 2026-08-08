import sys

with open("ui/dialogs/client_details_dialog.py", "r", encoding="utf-8") as f:
    content = f.read()

local_imports = """        from PySide6.QtWidgets import QSplitter, QWidget, QHeaderView
        from PySide6.QtCore import Qt

"""
content = content.replace(local_imports, "")

import_target = """from PySide6.QtWidgets import (
    QAbstractItemView,"""
import_replacement = """from PySide6.QtWidgets import (
    QSplitter,
    QHeaderView,
    QAbstractItemView,"""
content = content.replace(import_target, import_replacement)

with open("ui/dialogs/client_details_dialog.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Removed local Qt import and updated global imports.")
