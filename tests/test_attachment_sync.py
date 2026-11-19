"""Phase 12 tests: path-only attachment metadata sync.

Attachment rows carry metadata only (id, names, size, mime, relative path) -
never file bytes or absolute host paths. Writes on the host append change-log
entries so clients mirror the metadata; offline clients render attachment
lists straight from their SQLite cache without any network call.
"""

import base64
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.attachments import AttachmentService
from core.network.client import RemoteDatabase
from core.network.server import _check_permission

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

_SNAPSHOT_ROW = (
    9, 'sale', 12, 'plan.pdf', 'plan', 'desc', 'cat',
    'application/pdf', 1234, 'sale/12/ab.pdf',
    '2026-08-05 10:00:00', '2026-08-05 10:00:00',
)

_SNAPSHOT_KEYS = {
    'id', 'entity_type', 'entity_id', 'original_filename', 'display_name',
    'description', 'category', 'mime_type', 'file_size', 'relative_path',
    'created_at', 'modified_at',
}


class _AttachmentCursor:
    """Fake cursor serving the attachment + change_log SQL used by
    AttachmentService so the recording logic runs against real SQL text."""

    def __init__(self):
        self.executed = []
        self.fetchone_value = None
        self.description = None
        self.rowcount = 1
        self._record_row = ('sale', 12, 'sale/12/ab.pdf')
        self._inserted = None

    def execute(self, sql, params=()):
        normalized = ' '.join(sql.lower().split())
        self.executed.append((normalized, params))
        self.fetchone_value = None
        self.description = None
        self.rowcount = 1
        if normalized.startswith('insert into attachments'):
            self._inserted = params
            self.fetchone_value = (9,)
        elif normalized.startswith('select id, entity_type'):
            self.fetchone_value = self._snapshot_from_insert()
        elif normalized.startswith('select entity_type'):
            self.fetchone_value = self._record_row
        elif normalized.startswith('insert into change_log'):
            self.fetchone_value = (77,)
        elif normalized.startswith('delete from attachments'):
            self.rowcount = 1

    def _snapshot_from_insert(self):
        if getattr(self, '_inserted', None) is None:
            return _SNAPSHOT_ROW
        (entity_type, entity_id, original, display_name, description,
         category, mime, file_size, rel) = self._inserted
        return (
            9, entity_type, entity_id, original, display_name, description,
            category, mime, file_size, rel,
            '2026-08-05 10:00:00', '2026-08-05 10:00:00',
        )

    def fetchone(self):
        return self.fetchone_value

    def fetchall(self):
        return []


class _AttachmentDB:
    def __init__(self):
        self.cursor = _AttachmentCursor()
        self.conn = SimpleNamespace(commit=lambda: None, rollback=lambda: None)
        self.changes = []

    def record_change(self, section, row_id, operation, payload):
        self.changes.append((section, row_id, operation, payload))


class AttachmentServiceRecordingTests(unittest.TestCase):
    def test_snapshot_is_metadata_only_with_relative_path(self):
        service = AttachmentService(_AttachmentDB())
        snap = service._snapshot(9)
        self.assertEqual(set(snap), _SNAPSHOT_KEYS)
        self.assertEqual(snap['id'], 9)
        self.assertEqual(snap['relative_path'], 'sale/12/ab.pdf')
        self.assertNotIn(':', snap['relative_path'])
        self.assertNotIn('\\', snap['relative_path'])
        self.assertNotIn('content', snap)
        self.assertNotIn('bytes', snap)
        self.assertNotIn('data', snap)

    def test_upload_records_upsert_with_metadata_payload(self):
        import shutil
        database = _AttachmentDB()
        tmp = tempfile.mkdtemp(prefix='pylocalinventory-att-sync-')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with patch('core.attachments.storage_root', return_value=Path(tmp)):
            service = AttachmentService(database)
            attachment_id = service.upload(
                'sale', 12, 'plan.pdf',
                base64.b64encode(_PNG_BYTES).decode('ascii'),
            )
        self.assertEqual(attachment_id, 9)
        self.assertEqual(
            database.changes[-1][:3], ('attachments', 9, 'upsert')
        )
        payload = database.changes[-1][3]
        self.assertEqual(set(payload), _SNAPSHOT_KEYS)
        self.assertEqual(payload['entity_type'], 'sale')
        self.assertEqual(payload['entity_id'], 12)
        self.assertEqual(payload['mime_type'], 'image/png')
        stored = list((Path(tmp) / 'sale' / '12').glob('*.png'))
        self.assertEqual(len(stored), 1)
        self.assertEqual(
            Path(payload['relative_path']).name, stored[0].name,
        )
        self.assertEqual(payload['relative_path'], f'sale/12/{stored[0].name}')

    def test_update_records_upsert_when_changed(self):
        database = _AttachmentDB()
        service = AttachmentService(database)
        self.assertTrue(service.update(9, display_name='Renamed'))
        self.assertEqual(
            database.changes[-1][:3], ('attachments', 9, 'upsert')
        )

    def test_delete_records_delete_change(self):
        import shutil
        database = _AttachmentDB()
        tmp = tempfile.mkdtemp(prefix='pylocalinventory-att-sync-')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with patch('core.attachments.storage_root', return_value=Path(tmp)):
            service = AttachmentService(database)
            service.delete(9)
        self.assertEqual(
            database.changes[-1][:3], ('attachments', 9, 'delete')
        )
        self.assertIsNone(database.changes[-1][3])


class AttachmentSyncPermissionTests(unittest.TestCase):
    @staticmethod
    def _read_user(*sections):
        return {
            "is_superadmin": False,
            "permissions": {
                section: {"read": True, "write": False, "delete": False}
                for section in sections
            },
        }

    def test_attachments_stream_allowed_with_either_entity_read(self):
        for sections in (('Clients',), ('Sales',), ('Clients', 'Sales')):
            allowed, _ = _check_permission(
                self._read_user(*sections),
                'get_changes', ['attachments', 0, 100], {},
            )
            self.assertTrue(allowed)

    def test_attachments_stream_denied_without_entity_read(self):
        allowed, _ = _check_permission(
            self._read_user('Products'), 'get_changes', ['attachments', 0, 100], {},
        )
        self.assertFalse(allowed)

    def test_attachments_stream_superadmin_allowed(self):
        allowed, _ = _check_permission(
            {"is_superadmin": True, "permissions": {}},
            'get_changes', ['attachments'], {},
        )
        self.assertTrue(allowed)


class _OfflineClient(RemoteDatabase):
    def __init__(self, cache):
        self.cache = cache
        self.offline = False
        self.rpc_calls = []

    def _call(self, method, args=None, kwargs=None, timeout=10):
        self.rpc_calls.append((method, args))
        raise RuntimeError('network down')


class _FakeSyncClient(RemoteDatabase):
    def __init__(self, cache, responses):
        self.cache = cache
        self.offline = False
        self._responses = list(responses)

    def get_changes(self, section, since_seq=0, limit=500, timeout=4):
        if not self._responses:
            return {'changes': [], 'last_seq': since_seq}
        return self._responses.pop(0)


class AttachmentClientCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        from core.cache_manager import CacheManager
        self.cache = CacheManager(
            host='192.168.1.10', port='8765', username='alice',
            db_path=os.path.join(self.temp_dir.name, 'cache.db'),
        )
        self.addCleanup(self.cache.close)
        self.cache.store_records('attachments', [
            {
                'id': 1, 'entity_type': 'sale', 'entity_id': 12,
                'original_filename': 'plan.pdf', 'display_name': 'plan',
                'description': '', 'category': '', 'mime_type': 'application/pdf',
                'file_size': 10, 'relative_path': 'sale/12/x.pdf',
                'created_at': '2026-08-05 09:00:00', 'modified_at': '2026-08-05 09:00:00',
            },
            {
                'id': 2, 'entity_type': 'client', 'entity_id': 7,
                'original_filename': 'photo.jpg', 'display_name': 'photo',
                'description': '', 'category': '', 'mime_type': 'image/jpeg',
                'file_size': 20, 'relative_path': 'client/7/y.jpg',
                'created_at': '2026-08-04 09:00:00', 'modified_at': '2026-08-04 09:00:00',
            },
        ])

    def test_offline_list_renders_from_cache_without_network(self):
        client = _OfflineClient(self.cache)
        client.offline = True
        records = client.list_attachments('sale', 12)
        self.assertEqual([r['id'] for r in records], [1])
        self.assertEqual(client.rpc_calls, [])

    def test_online_list_queries_host(self):
        client = _OfflineClient(self.cache)
        with self.assertRaises(RuntimeError):
            client.list_attachments('sale', 12)
        self.assertEqual(client.rpc_calls, [('list_attachments', ['sale', 12])])

    def test_attachment_payloads_sync_into_cache(self):
        client = _FakeSyncClient(self.cache, [{
            'changes': [
                {
                    'seq': 1, 'row_id': 3, 'operation': 'upsert',
                    'payload': {
                        'id': 3, 'entity_type': 'client', 'entity_id': 7,
                        'original_filename': 'notes.pdf', 'display_name': 'notes',
                        'description': '', 'category': '',
                        'mime_type': 'application/pdf', 'file_size': 5,
                        'relative_path': 'client/7/n.pdf',
                        'created_at': '2026-08-05 10:00:00',
                        'modified_at': '2026-08-05 10:00:00',
                    },
                },
            ],
            'last_seq': 1,
        }])
        result = client.sync_section('attachments')
        self.assertEqual(result['applied'], 1)
        records = self.cache.get_records('attachments')
        self.assertEqual(records[3]['entity_type'], 'client')
        self.assertEqual(records[3]['relative_path'], 'client/7/n.pdf')
        self.assertEqual(self.cache.get_sync_state('attachments'), 1)


if __name__ == '__main__':
    unittest.main()
