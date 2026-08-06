import unittest
import time
from unittest.mock import MagicMock

class TestRecentChanges(unittest.TestCase):
    def test_get_items_by_operation_ids(self):
        from core.database import Database
        # Create a mock database instance without initializing the connection
        db = Database.__new__(Database)
        db.cursor = MagicMock()
        db.cursor.description = [('ID',), ('sales_id',), ('quantity',)]
        db.cursor.fetchall.return_value = [
            (1, 100, 5),
            (2, 100, 10),
            (3, 200, 1)
        ]
        db.registered_classes = ['Sales_Items']
        
        res = db.get_items_by_operation_ids([100, 200], 'Sales_Items')
        self.assertIn(100, res)
        self.assertIn(200, res)
        self.assertEqual(len(res[100]), 2)
        self.assertEqual(len(res[200]), 1)
        
        # Verify the format of the output
        self.assertEqual(res[100][0]['quantity'], 5)

    def test_get_attachment_thumbnails_bulk(self):
        from core.attachments import AttachmentService
        service = AttachmentService.__new__(AttachmentService)
        service.thumbnail = MagicMock(side_effect=lambda aid, max_size: f"thumb_{aid}")
        
        res = service.thumbnails([1, 2, 3])
        self.assertIsInstance(res, dict)
        self.assertEqual(res[1], "thumb_1")
        self.assertEqual(res[2], "thumb_2")
        self.assertEqual(res[3], "thumb_3")

    def test_memory_utils(self):
        from core.memory_utils import process_memory_mb
        mem = process_memory_mb(refresh=True)
        self.assertIsInstance(mem, float)
        self.assertGreaterEqual(mem, 0.0)

if __name__ == '__main__':
    unittest.main()
