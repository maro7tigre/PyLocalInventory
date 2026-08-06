with open("tests/test_recent_changes_full.py", "r", encoding="utf-8") as f:
    lines = f.read()

lines = lines.replace(
"""        dialog.parameter_widgets = {}""",
"""        dialog.parameter_widgets = {}
        dialog.save_btn = MagicMock()"""
)

lines = lines.replace(
"""        # Trigger save
        dialog._save_changes_impl()""",
"""        # Trigger save
        dialog._save_changes()"""
)

lines = lines.replace(
"""        class MockDataManager:
            def __init__(self, db):
                self.database = db
                self.table_columns = ["product_name", "quantity", "price"]
                
        self.data_manager = MockDataManager(self.db)
        
        self.table_widget = OperationsTableWidget(self.data_manager, None)""",
"""        self.table_widget = OperationsTableWidget(DummyItem, self.db)"""
)

with open("tests/test_recent_changes_full.py", "w", encoding="utf-8") as f:
    f.write(lines)
