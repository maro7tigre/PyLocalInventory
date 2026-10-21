"""Regression tests for attachment previews on remote LAN clients.

The host used to bypass the LAN permission table, while a remote client hit
two separate problems:

* thumbnail RPCs were checked with a stale owner-argument index, so regular
  users were denied; and
* JSON turns the bulk thumbnail dict's integer ids into strings, so even an
  allowed response could not be matched to an attachment row.

These tests stay entirely in-process (no PostgreSQL/network server) and cover
the permission table, RemoteDatabase normalization/caching, the background
worker, and rendering in AttachmentPanel.
"""

import base64
import os
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from core.attachments import AttachmentService
from core.network.client import RemoteDatabase
from core.network.protocol import PermissionDeniedError
from core.network.server import _check_permission
from ui.widgets.attachments_widget import (
    AttachmentPanel,
    _AttachmentFetchWorker,
    _decode_thumbnail_payloads,
)


def _png_bytes(width=8, height=4, color=Qt.red):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(color)
    buffer = QBuffer()
    assert buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def _record(attachment_id, name, mime_type="image/png"):
    return {
        "id": attachment_id,
        "entity_type": "client",
        "entity_id": 1,
        "client_id": 1,
        "sale_id": None,
        "original_filename": name,
        "display_name": name,
        "description": "",
        "category": "",
        "mime_type": mime_type,
        "file_size": 128,
        "relative_path": f"client/1/{attachment_id}.png",
        "created_at": "2026-10-01 10:00:00",
        "modified_at": "2026-10-01 10:00:00",
    }


def _remote_database(responses):
    """Build a RemoteDatabase without a real login/network connection."""
    remote = RemoteDatabase.__new__(RemoteDatabase)
    remote.host = "192.0.2.10"
    remote.port = 8765
    remote.offline = False
    remote.cache = None
    remote._attachment_thumbnail_cache = OrderedDict()
    remote.calls = []

    def rpc(method, args=None, kwargs=None, timeout=10):
        remote.calls.append((method, args))
        value = responses[method]
        return value(args) if callable(value) else value

    remote._call = rpc
    return remote


class AttachmentThumbnailPermissionTests(unittest.TestCase):
    @staticmethod
    def _user(*sections, action="read"):
        return {
            "is_superadmin": False,
            "permissions": {
                section: {"read": True, "write": action == "write", "delete": False}
                for section in sections
            },
        }

    def test_attachment_fetch_rpcs_follow_attachment_read_scope(self):
        calls = (
            ("get_attachment", [42]),
            ("download_attachment", [42]),
            ("get_attachment_thumbnail", [42]),
            ("get_attachment_thumbnails_bulk", [[42, 43]]),
        )
        for method, args in calls:
            for section in ("Clients", "Sales"):
                allowed, reason = _check_permission(
                    self._user(section), method, args, {}
                )
                self.assertTrue(allowed, f"{method} denied with {section} read: {reason}")
            denied, _ = _check_permission(self._user(), method, args, {})
            self.assertFalse(denied, f"{method} allowed without an attachment scope")

    def test_rename_attachment_follows_attachment_write_scope(self):
        args = [42, "renamed.png"]
        for section in ("Clients", "Sales"):
            allowed, reason = _check_permission(
                self._user(section, action="write"), "update_attachment", args, {}
            )
            self.assertTrue(allowed, f"update denied with {section} write: {reason}")
        denied, _ = _check_permission(
            self._user("Clients"), "update_attachment", args, {}
        )
        self.assertFalse(denied)


class RemoteThumbnailCacheTests(unittest.TestCase):
    def test_bulk_thumbnail_json_keys_are_normalized_and_cached(self):
        remote = _remote_database({
            "get_attachment_thumbnails_bulk": {"1": "thumb-1", "2": "thumb-2"},
        })
        self.assertEqual(
            remote.get_attachment_thumbnails_bulk([1, 2]),
            {1: "thumb-1", 2: "thumb-2"},
        )
        self.assertEqual(
            remote.get_attachment_thumbnails_bulk([1, 2]),
            {1: "thumb-1", 2: "thumb-2"},
        )
        self.assertEqual(len(remote.calls), 1)

        remote._call = lambda method, args=None, **kwargs: (
            remote.calls.append((method, args)) or {"3": "thumb-3"}
        )
        self.assertEqual(
            remote.get_attachment_thumbnails_bulk([1, 2, 3]),
            {1: "thumb-1", 2: "thumb-2", 3: "thumb-3"},
        )
        self.assertEqual(remote.calls[-1], ("get_attachment_thumbnails_bulk", [[3]]))

    def test_single_thumbnail_uses_cache_and_never_needs_host_paths(self):
        remote = _remote_database({
            "get_attachment_thumbnail": lambda _args: "single-thumb",
        })
        self.assertEqual(remote.get_attachment_thumbnail(7), "single-thumb")
        self.assertEqual(remote.get_attachment_thumbnail(7), "single-thumb")
        self.assertEqual(remote.calls, [("get_attachment_thumbnail", [7])])

    def test_legacy_host_403_falls_back_to_allowed_attachment_downloads(self):
        payload = base64.b64encode(_png_bytes()).decode("ascii")
        remote = _remote_database({})

        def rpc(method, args=None, **kwargs):
            remote.calls.append((method, args))
            if method == "get_attachment_thumbnails_bulk":
                raise PermissionDeniedError("You don't have permission")
            if method == "download_attachment":
                return payload
            raise AssertionError(f"unexpected RPC {method}")

        remote._call = rpc
        self.assertEqual(
            remote.get_attachment_thumbnails_bulk([1, 2]),
            {1: payload, 2: payload},
        )
        self.assertEqual(
            remote.calls,
            [
                ("get_attachment_thumbnails_bulk", [[1, 2]]),
                ("download_attachment", [1]),
                ("download_attachment", [2]),
            ],
        )
        # Full files must not be retained by the small-thumbnail LRU.
        self.assertEqual(len(remote._attachment_thumbnail_cache), 0)

    def test_offline_client_returns_cached_thumbnails_without_rpc(self):
        remote = _remote_database({
            "get_attachment_thumbnails_bulk": {"1": "cached"},
        })
        remote.get_attachment_thumbnails_bulk([1])
        remote.calls.clear()
        remote.offline = True
        self.assertEqual(remote.get_attachment_thumbnails_bulk([1, 2]), {1: "cached"})
        self.assertEqual(remote.calls, [])


class RemoteThumbnailRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _panel(self, database):
        with patch.object(AttachmentPanel, "refresh", lambda _self: None):
            panel = AttachmentPanel(database, "sale", 1)
        panel.refresh = lambda: None
        return panel

    def test_worker_decodes_string_keyed_remote_thumbnails(self):
        record = _record(1, "photo.png")
        payload = base64.b64encode(_png_bytes()).decode("ascii")
        database = SimpleNamespace(
            list_attachments=lambda *_args: [record],
            get_attachment_thumbnails_bulk=lambda _ids: {"1": payload},
        )
        received = []
        worker = _AttachmentFetchWorker(database, "sale", 1, "", "All files")
        worker.finished.connect(lambda records, thumbs: received.append((records, thumbs)))
        worker.run()

        self.assertEqual(received[0][0], [record])
        thumbnails = received[0][1]
        self.assertEqual(list(thumbnails), [1])
        self.assertIsInstance(thumbnails[1], QImage)
        self.assertFalse(thumbnails[1].isNull())

    def test_worker_skips_thumbnails_already_held_by_the_panel(self):
        record = _record(1, "photo.png")
        calls = []
        database = SimpleNamespace(
            list_attachments=lambda *_args: [record],
            get_attachment_thumbnails_bulk=lambda ids: calls.append(ids) or {},
        )
        received = []
        worker = _AttachmentFetchWorker(
            database, "sale", 1, "", "All files", known_thumbnail_ids={1},
        )
        worker.finished.connect(lambda records, thumbs: received.append(thumbs))
        worker.run()

        self.assertEqual(calls, [])
        self.assertEqual(received, [{}])

    def test_worker_scales_legacy_full_image_to_thumbnail_size(self):
        record = _record(1, "photo.png")
        payload = base64.b64encode(_png_bytes(400, 200)).decode("ascii")
        database = SimpleNamespace(
            list_attachments=lambda *_args: [record],
            get_attachment_thumbnails_bulk=lambda _ids: {1: payload},
        )
        received = []
        worker = _AttachmentFetchWorker(database, "sale", 1, "", "All files")
        worker.finished.connect(lambda records, thumbs: received.append(thumbs))
        worker.run()

        image = received[0][1]
        self.assertLessEqual(max(image.width(), image.height()), 160)
        self.assertAlmostEqual(image.width() / image.height(), 2.0, places=2)

    def test_rendered_preview_uses_remote_thumbnail_without_gui_rpc(self):
        record = _record(1, "photo.png")
        database = SimpleNamespace(
            list_attachments=lambda *_args: [record],
            get_attachment_thumbnails_bulk=lambda _ids: {},
        )
        panel = self._panel(database)
        fallback_calls = []
        database.get_attachment_thumbnail = lambda attachment_id: fallback_calls.append(
            attachment_id
        )

        image = QImage.fromData(_png_bytes(64, 32))
        panel._render_attachments([record], {1: image})

        item = panel.table.item(0, 0)
        self.assertFalse(item.icon().isNull())
        self.assertEqual(panel.table.rowHeight(0), 112)
        self.assertEqual(fallback_calls, [])

        # A refresh without a payload keeps the already-decoded preview.
        panel._render_attachments([record], {})
        self.assertFalse(panel.table.item(0, 0).icon().isNull())

    def test_invalid_or_missing_image_shows_empty_state_without_crashing(self):
        record = _record(1, "broken.png")
        database = SimpleNamespace(
            list_attachments=lambda *_args: [record],
            get_attachment_thumbnails_bulk=lambda _ids: {},
        )
        panel = self._panel(database)

        self.assertEqual(_decode_thumbnail_payloads({"1": "not-an-image"}), {})
        panel._render_attachments([record], {"1": "not-an-image"})
        item = panel.table.item(0, 0)
        self.assertTrue(item.icon().isNull())
        self.assertEqual(item.text(), "Unavailable")

    def test_host_thumbnail_service_preserves_aspect_ratio_for_png_and_jpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "client" / "1"
            source.mkdir(parents=True)
            service = AttachmentService.__new__(AttachmentService)
            service.database = SimpleNamespace()
            service._record = lambda _attachment_id: (
                "client", 1, "client/1/picture.png",
            )
            image = QImage(400, 200, QImage.Format_RGB32)
            image.fill(Qt.blue)
            self.assertTrue(image.save(str(source / "picture.png"), "PNG"))
            self.assertTrue(image.save(str(source / "picture.jpg"), "JPEG"))

            with patch("core.attachments.storage_root", return_value=root):
                png = service.thumbnail(1)
                service._record = lambda _attachment_id: (
                    "client", 1, "client/1/picture.jpg",
                )
                jpeg = service.thumbnail(2)

            for payload in (png, jpeg):
                self.assertIsNotNone(payload)
                decoded = QImage.fromData(base64.b64decode(payload))
                self.assertFalse(decoded.isNull())
                self.assertLessEqual(max(decoded.width(), decoded.height()), 160)
                self.assertAlmostEqual(decoded.width() / decoded.height(), 2.0, places=2)


if __name__ == "__main__":
    unittest.main()
