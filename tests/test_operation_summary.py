import unittest
from unittest.mock import MagicMock
from core.database import Database

class TestOperationSummary(unittest.TestCase):
    def setUp(self):
        pm = MagicMock()
        pm.selected_profile.schema_name = "test_schema"
        self.db = Database(pm)
        self.db.conn = MagicMock()
        self.cur_mock = MagicMock()
        self.db.cursor = self.cur_mock
        self.db.conn.cursor.return_value = self.cur_mock

    def test_operation_summary_sales(self):
        # Execute the method for Sales
        self.db.get_operation_summary_items("Sales")
        
        # Verify the generated SQL
        calls = self.cur_mock.execute.call_args_list
        self.assertGreater(len(calls), 0)
        query = calls[0][0][0]
        
        # Assert specific Sales logic is present
        self.assertIn("COALESCE(STRING_AGG(COALESCE(si.information, ''), ', ' ORDER BY si.id), '') AS information", query)
        self.assertIn("COALESCE(SUM(si.production), 0) AS total_production", query)
        self.assertIn("FROM sales_items si", query)
        self.assertIn("JOIN sales i ON i.id = si.sales_id", query)

    def test_operation_summary_imports(self):
        # Execute the method for Imports
        self.db.get_operation_summary_items("Imports")
        
        # Verify the generated SQL
        calls = self.cur_mock.execute.call_args_list
        self.assertGreater(len(calls), 0)
        query = calls[0][0][0]
        
        # Assert specific Imports logic is present (no si.information, no si.production)
        self.assertIn("'' AS information", query)
        self.assertIn("0 AS total_production", query)
        self.assertIn("FROM import_items si", query)
        self.assertIn("JOIN imports i ON i.id = si.import_id", query)
        
        # Assert it DOES NOT contain the failing si.information aggregation
        self.assertNotIn("si.information", query)
        self.assertNotIn("si.production", query)

if __name__ == '__main__':
    unittest.main()
