import base64
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication
from core.attachments import display_filename, validate_bytes
from core.network.server import _check_permission
from classes.sales_class import SalesClass
from ui.widgets.attachments_widget import AttachmentPanel


class AttachmentSafetyTests(unittest.TestCase):
    def test_validates_real_signatures_not_extensions(self):
        mime, suffix = validate_bytes(b'\x89PNG\r\n\x1a\nminimal', 'malware.exe')
        self.assertEqual((mime, suffix), ('image/png', '.png'))
        with self.assertRaises(ValueError):
            validate_bytes(b'MZ executable', 'photo.jpg')

    def test_sanitizes_machine_unsafe_display_names(self):
        self.assertEqual(display_filename('../../CON?.pdf'), 'CON_.pdf')
        self.assertNotIn('..', display_filename('../secret.pdf'))

    def test_lan_attachment_permissions_follow_owner_scope(self):
        user = {'is_superadmin': False, 'permissions': {'Clients': {'read': True, 'write': True, 'delete': True}, 'Sales': {'read': True, 'write': False, 'delete': False}}}
        self.assertTrue(_check_permission(user, 'list_attachments', ['client', 1], {})[0])
        self.assertFalse(_check_permission(user, 'upload_attachment', ['sale', 1], {})[0])

    def test_sale_upload_is_mirrored_to_linked_client(self):
        class Cursor:
            def execute(self, *_args):
                pass
            def fetchone(self):
                return (24,)
        class Database:
            cursor = Cursor()
            conn = SimpleNamespace(rollback=lambda: None)
            def __init__(self):
                self.uploads = []
            def upload_attachment(self, *args):
                self.uploads.append(args)
        database = Database()
        panel = SimpleNamespace(database=database, entity_type='sale', entity_id=8)
        AttachmentPanel._upload_bytes(panel, 'proof.png', b'png-data')
        self.assertEqual([upload[0:2] for upload in database.uploads], [('sale', 8), ('client', 24)])

    def test_sales_model_persists_client_id(self):
        self.assertIn('client_id', SalesClass(0, None).get_visible_parameters('database'))

    def test_client_sales_table_filters_by_client_id(self):
        class Cursor:
            def __init__(self): self.calls = []
            def execute(self, sql, params=()): self.calls.append((sql, params))
            def fetchall(self): return [(17, 'Kitchen order', '2026-07-24', 20, 1000)]
        class Database:
            def __init__(self): self.cursor = Cursor(); self.conn = SimpleNamespace(rollback=lambda: None)
            def list_attachments(self, *_args): return []
        app = QApplication.instance() or QApplication([])
        database = Database()
        panel = AttachmentPanel(database, 'client', 42)
        self.assertEqual(panel.client_sales_table.rowCount(), 1)
        self.assertEqual(database.cursor.calls[-1][1], (42,))
        self.assertEqual(panel.client_sales_table.item(0, 0).text(), '17')
        panel.deleteLater()
