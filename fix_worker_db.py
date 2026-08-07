import re
from core.database import Database

def safe_replace(filepath, replacements):
    with open(filepath, 'r', encoding='utf-8') as f:
        code = f.read()
    
    for old, new in replacements:
        if old in code:
            code = code.replace(old, new)
        else:
            print(f"Warning: Could not find block in {filepath}")
            print(f"--- Expected:\n{old}")
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(code)

replacements = [
(
"""    def _create_worker_database(self):
        \"\"\"Create an independent database connection for background refreshes.\"\"\"
        if self.database is None:
            return None
        if self.database.__class__.__name__ == 'RemoteDatabase':
            return self.database

        worker_db = Database(self.database.profile_manager)
        worker_db.language = getattr(self.database, 'language', 'en')
        worker_db.registered_classes = self.database.registered_classes
        if getattr(self.database, 'profile_manager', None):
            if not worker_db.connect():
                raise RuntimeError("Failed to connect worker database")
        return worker_db""",
"""    def _create_worker_database(self):
        \"\"\"Create an independent database connection for background refreshes.\"\"\"
        if self.database is None:
            return None
        if self.database.__class__.__name__ == 'RemoteDatabase':
            return self.database

        from core.database import Database
        worker_db = Database(self.database.profile_manager)
        worker_db.language = getattr(self.database, 'language', 'en')
        worker_db.registered_classes = self.database.registered_classes
        # DO NOT connect synchronously on the GUI thread.
        # Connection will be established inside the worker's fetch() closure.
        return worker_db"""
),
(
"""        def fetch():
            if hasattr(database, 'get_operation_summary_items') and section in ('Sales', 'Imports'):""",
"""        def fetch():
            # Establish connection inside the worker thread if not connected
            if getattr(database, 'profile_manager', None) and not getattr(database, 'conn', None):
                if not database.connect():
                    raise RuntimeError("Failed to connect worker database on background thread")
            
            if hasattr(database, 'get_operation_summary_items') and section in ('Sales', 'Imports'):"""
)
]

safe_replace("ui/tabs/base_tab.py", replacements)
print("Patched _create_worker_database")
