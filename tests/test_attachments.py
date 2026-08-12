import base64
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QImage
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
                return (24, 'linked-client')
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
        class Database:
            def __init__(self): self.client_sales_calls = []
            def list_attachments(self, *_args): return []
            def get_client_sales(self, client_id):
                self.client_sales_calls.append(client_id)
                return [[17, 'DE-2026-3', '2026-07-24', 20, 1000]]
        app = QApplication.instance() or QApplication([])
        database = Database()
        panel = AttachmentPanel(database, 'client', 42)
        # get_client_sales() now runs on a background QThread (never on the
        # GUI thread - see attachments_widget._ClientSalesFetchWorker).
        # database.client_sales_calls is mutated directly on that thread, so
        # polling it alone races the queued 'finished' signal that actually
        # populates the table - wait for the thread to fully wind down
        # instead (its cleanup chain runs strictly after the render slot).
        deadline = time.time() + 2.0
        while panel._sales_thread is not None and time.time() < deadline:
            app.processEvents()
            time.sleep(0.01)
        self.assertEqual(panel.client_sales_table.rowCount(), 1)
        self.assertEqual(database.client_sales_calls, [42])
        self.assertEqual(panel.client_sales_table.item(0, 0).text(), '17')
        # Column 1 is now Devis N° (replaces the old Notes column) and shows
        # the reference with an explicit N° marker, never a bare-looking ID.
        headers = [
            panel.client_sales_table.horizontalHeaderItem(c).text()
            for c in range(panel.client_sales_table.columnCount())
        ]
        self.assertEqual(headers[1], 'Devis N°')
        self.assertEqual(panel.client_sales_table.item(0, 1).text(), 'DE N°-2026-3')
        panel.deleteLater()

    @patch('ui.widgets.attachments_widget.QMessageBox.information')
    @patch('ui.widgets.attachments_widget._scan_with_windows_wia')
    def test_successful_windows_scan_uploads_png(self, scan, information):
        uploads = []
        refreshes = []

        def create_scan(path):
            # Some WIA drivers return BMP data even when PNG was requested and
            # the destination filename ends in .png.
            image = QImage(2, 2, QImage.Format_RGB32)
            image.fill(0xFFFFFFFF)
            self.assertTrue(image.save(str(path), 'BMP'))
            self.assertTrue(path.read_bytes().startswith(b'BM'))
            return SimpleNamespace(returncode=0, stdout='', stderr='')

        scan.side_effect = create_scan
        panel = SimpleNamespace(
            _upload_bytes=lambda filename, data: uploads.append((filename, data)),
            refresh=lambda: refreshes.append(True),
        )
        with patch('ui.widgets.attachments_widget.sys.platform', 'win32'):
            AttachmentPanel.scan_document(panel)

        self.assertEqual(len(uploads), 1)
        self.assertTrue(uploads[0][0].startswith('scan-'))
        self.assertTrue(uploads[0][0].endswith('.png'))
        self.assertTrue(uploads[0][1].startswith(b'\x89PNG'))
        self.assertEqual(refreshes, [True])
        information.assert_called_once()

    @patch('ui.widgets.attachments_widget.QMessageBox.information')
    @patch('ui.widgets.attachments_widget._scan_with_windows_wia')
    def test_cancelled_windows_scan_does_not_upload(self, scan, information):
        scan.return_value = SimpleNamespace(returncode=2, stdout='', stderr='')
        panel = SimpleNamespace(
            _upload_bytes=lambda *_args: self.fail('Cancelled scan must not upload a file'),
            refresh=lambda: self.fail('Cancelled scan must not refresh attachments'),
        )
        with patch('ui.widgets.attachments_widget.sys.platform', 'win32'):
            AttachmentPanel.scan_document(panel)
        information.assert_not_called()
