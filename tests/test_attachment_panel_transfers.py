import base64
import os
import threading
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QEvent, QIODevice, QItemSelectionModel, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from ui.widgets.attachments_widget import AttachmentPanel, _active_attachment_jobs, _active_attachment_threads


class _RemoteAttachmentDatabase:
    def __init__(self, payloads, delay=0):
        self.payloads = payloads
        self.delay = delay
        self.download_calls = []
        self.upload_calls = []

    def list_attachments(self, *_args):
        return []

    def get_client_sales(self, *_args):
        return []

    def download_attachment(self, attachment_id):
        self.download_calls.append(attachment_id)
        if self.delay:
            time.sleep(self.delay)
        payload = self.payloads[attachment_id]
        if isinstance(payload, Exception):
            raise payload
        return base64.b64encode(payload).decode("ascii")

    def upload_attachment(self, *args, **kwargs):
        self.upload_calls.append((args, kwargs))
        return 1


def _wait_until(predicate, timeout_ms=3000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        QTest.qWait(5)
    return predicate()


def _wait_for_transfer(panel, timeout_ms=3000):
    thread = panel._transfer_thread
    assert thread is not None
    assert thread.wait(timeout_ms), "attachment transfer QThread did not stop in time"
    assert _wait_until(lambda: panel._transfer_thread is None, timeout_ms)


def _panel(database, entity_type="sale"):
    QApplication.instance() or QApplication([])
    with patch.object(AttachmentPanel, "refresh", lambda _self: None), patch.object(
        AttachmentPanel, "refresh_sales", lambda _self: None,
    ):
        panel = AttachmentPanel(database, entity_type, 1)
    panel.refresh = lambda: None
    return panel


def _select(panel, records):
    panel._render_attachments(records, {})
    panel.table.clearSelection()
    for row in range(len(records)):
        index = panel.table.model().index(row, 0)
        panel.table.selectionModel().select(
            index, QItemSelectionModel.Select | QItemSelectionModel.Rows,
        )


def _record(attachment_id, name, mime="application/pdf"):
    return {
        "id": attachment_id, "display_name": name, "original_filename": name,
        "mime_type": mime, "file_size": 1, "created_at": "2026-10-01",
    }


def _png_bytes():
    image = QImage(3, 2, QImage.Format_RGB32)
    image.fill(Qt.red)
    buffer = QBuffer()
    assert buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_export_multiple_files_preserves_content_and_cleans_transfer():
    database = _RemoteAttachmentDatabase({1: b"first", 2: b"second"})
    panel = _panel(database)
    records = [_record(1, "first.pdf"), _record(2, "second.pdf")]
    _select(panel, records)
    with tempfile.TemporaryDirectory() as directory:
        targets = iter([str(Path(directory) / "first.pdf"), str(Path(directory) / "second.pdf")])
        with patch("ui.widgets.attachments_widget.QFileDialog.getSaveFileName", side_effect=lambda *_: (next(targets), "")):
            panel.export_selected()
        _wait_for_transfer(panel)
        assert (Path(directory) / "first.pdf").read_bytes() == b"first"
        assert (Path(directory) / "second.pdf").read_bytes() == b"second"
        assert not list(Path(directory).glob("tmp*"))
    assert not _active_attachment_jobs
    assert not _active_attachment_threads
    panel.shutdown()


def test_export_single_attachment_preserves_content_and_cleans_temporary_file():
    database = _RemoteAttachmentDatabase({1: b"single export payload"})
    panel = _panel(database)
    _select(panel, [_record(1, "single.pdf")])
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "single.pdf"
        with patch("ui.widgets.attachments_widget.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            panel.export_selected()
        _wait_for_transfer(panel)
        assert target.read_bytes() == b"single export payload"
        assert list(Path(directory).iterdir()) == [target]
    assert database.download_calls == [1]
    panel.shutdown()


def test_open_and_print_use_local_qurl_and_mocked_windows_callback(monkeypatch):
    database = _RemoteAttachmentDatabase({1: b"document to open", 2: b"document to print"})
    panel = _panel(database)
    opened, printed = [], []
    monkeypatch.setattr(
        "ui.widgets.attachments_widget.QDesktopServices.openUrl",
        lambda url: opened.append(url),
    )
    monkeypatch.setattr(os, "startfile", lambda path, action: printed.append((path, action)))
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TEMP": directory}):
        _select(panel, [_record(1, "open.pdf")])
        panel.open_selected()
        _wait_for_transfer(panel)
        assert Path(opened[0].toLocalFile()).read_bytes() == b"document to open"
        assert opened[0].isLocalFile()

        _select(panel, [_record(2, "print.pdf")])
        panel.print_selected()
        _wait_for_transfer(panel)
        assert Path(printed[0][0]).read_bytes() == b"document to print"
        assert printed[0][1] == "print"
    panel.shutdown()


def test_image_preview_decodes_and_displays_downloaded_image(monkeypatch):
    payload = _png_bytes()
    database = _RemoteAttachmentDatabase({1: payload})
    panel = _panel(database)
    _select(panel, [_record(1, "preview.png", "image/png")])
    dialogs = []

    def capture_preview(dialog):
        image_label = dialog.findChild(QLabel)
        assert image_label is not None
        pixmap = image_label.pixmap()
        assert pixmap is not None and not pixmap.isNull()
        dialogs.append(dialog.windowTitle())
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", capture_preview)
    panel.preview()
    _wait_for_transfer(panel)
    assert dialogs == ["preview.png"]
    assert database.download_calls == [1]
    panel.shutdown()


def test_clipboard_and_scanner_upload_valid_png_bytes(monkeypatch):
    image_payload = _png_bytes()
    database = _RemoteAttachmentDatabase({})
    panel = _panel(database, "client")
    clipboard_image = QImage.fromData(image_payload)
    clipboard = type("Clipboard", (), {"image": lambda self: clipboard_image})()
    monkeypatch.setattr(
        "ui.widgets.attachments_widget.QGuiApplication.clipboard",
        lambda: clipboard,
    )
    panel.paste_image()
    clipboard_thread = panel._transfer_thread
    clipboard_thread_destroyed = threading.Event()
    clipboard_thread.destroyed.connect(lambda *_args: clipboard_thread_destroyed.set())
    _wait_for_transfer(panel)
    assert _wait_until(clipboard_thread_destroyed.is_set)
    assert not _active_attachment_jobs
    assert not _active_attachment_threads

    def fake_scanner(output_path):
        Path(output_path).write_bytes(image_payload)
        return type("ScanResult", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr("ui.widgets.attachments_widget.sys.platform", "win32")
    monkeypatch.setattr("ui.widgets.attachments_widget._scan_with_windows_wia", fake_scanner)
    with tempfile.TemporaryDirectory() as directory, patch(
        "ui.widgets.attachments_widget.tempfile.tempdir", directory,
    ):
        panel.scan_document()
        scanner_thread = panel._transfer_thread
        scanner_thread_destroyed = threading.Event()
        scanner_thread.destroyed.connect(lambda *_args: scanner_thread_destroyed.set())
        _wait_for_transfer(panel)
        assert _wait_until(scanner_thread_destroyed.is_set)
        assert list(Path(directory).iterdir()) == []

    assert len(database.upload_calls) == 2
    for args, _kwargs in database.upload_calls:
        uploaded_image = QImage.fromData(base64.b64decode(args[3]))
        assert not uploaded_image.isNull()
        assert uploaded_image.size() == clipboard_image.size()
    assert database.upload_calls[0][0][2] == "clipboard-image.png"
    assert database.upload_calls[1][0][2].startswith("scan-")
    assert database.upload_calls[1][0][2].endswith(".png")
    panel.shutdown()


def test_repeated_clicks_are_rejected_while_transfer_is_active(monkeypatch):
    started, release = threading.Event(), threading.Event()

    class SlowDatabase(_RemoteAttachmentDatabase):
        def download_attachment(self, attachment_id):
            started.set()
            if not release.wait(2):
                raise TimeoutError("test did not release the active RPC")
            return super().download_attachment(attachment_id)

    database = SlowDatabase({1: b"only one request"})
    panel = _panel(database)
    _select(panel, [_record(1, "broken.pdf")])
    notices = []
    monkeypatch.setattr("ui.widgets.attachments_widget.QMessageBox.information", lambda *_args: notices.append(True))
    panel.open_selected()
    assert started.wait(2), "download RPC did not start in time"
    panel.open_selected()
    assert notices
    release.set()
    _wait_for_transfer(panel)
    assert database.download_calls == [1]
    assert not _active_attachment_jobs
    assert not _active_attachment_threads
    panel.shutdown()


def test_rpc_failure_does_not_leave_partial_export_or_temporary_file(monkeypatch):
    database = _RemoteAttachmentDatabase({1: RuntimeError("network interrupted")})
    panel = _panel(database)
    _select(panel, [_record(1, "broken.pdf")])
    warnings = []
    monkeypatch.setattr("ui.widgets.attachments_widget.QMessageBox.warning", lambda *_args: warnings.append(_args[-1]))
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "broken.pdf"
        with patch("ui.widgets.attachments_widget.QFileDialog.getSaveFileName", return_value=(str(target), "")):
            panel.export_selected()
        _wait_for_transfer(panel)
        assert not target.exists()
    assert database.download_calls == [1]
    assert not _active_attachment_jobs
    assert not _active_attachment_threads
    assert warnings
    panel.shutdown()


def test_shutdown_cancels_after_slow_active_transfer_and_skips_next_job():
    started, release = threading.Event(), threading.Event()

    class SlowDatabase(_RemoteAttachmentDatabase):
        def download_attachment(self, attachment_id):
            self.download_calls.append(attachment_id)
            if attachment_id == 1:
                started.set()
                if not release.wait(2):
                    raise TimeoutError("test did not release the active RPC")
            return base64.b64encode(self.payloads[attachment_id]).decode("ascii")

    database = SlowDatabase({1: b"current request", 2: b"must not start"})
    panel = _panel(database)
    records = [_record(1, "active.bin"), _record(2, "queued.bin")]
    completed = []
    panel._start_download([(records[0], None), (records[1], None)], completed.append)
    assert started.wait(2), "download RPC did not start in time"
    panel.shutdown()
    release.set()
    _wait_for_transfer(panel)
    assert database.download_calls == [1]
    assert not completed
    assert not _active_attachment_jobs
    assert not _active_attachment_threads


def test_destroying_widget_during_transfer_does_not_leak_thread_or_callback():
    started, release, callbacks = threading.Event(), threading.Event(), []

    class SlowDatabase(_RemoteAttachmentDatabase):
        def download_attachment(self, attachment_id):
            started.set()
            if not release.wait(2):
                raise TimeoutError("test did not release the active RPC")
            return super().download_attachment(attachment_id)

    database = SlowDatabase({1: b"destroy during transfer"})
    panel = _panel(database)
    thread_ref = None
    destroyed = threading.Event()
    panel.destroyed.connect(lambda *_args: destroyed.set())
    panel._start_download([(_record(1, "destroy.bin"), None)], callbacks.append)
    assert started.wait(2), "download RPC did not start in time"
    thread_ref = panel._transfer_thread
    thread_destroyed = threading.Event()
    thread_ref.destroyed.connect(lambda *_args: thread_destroyed.set())
    panel.shutdown()
    panel.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    release.set()
    assert thread_ref.wait(3000), "transfer thread did not stop after widget destruction"
    assert _wait_until(lambda: not _active_attachment_jobs and not _active_attachment_threads)
    assert _wait_until(thread_destroyed.is_set)
    assert destroyed.is_set()
    assert not callbacks


def test_repeated_exports_destroy_threads_and_leave_no_active_jobs():
    payloads = {index: f"attachment payload {index}".encode() for index in range(5)}
    database = _RemoteAttachmentDatabase(payloads)
    panel = _panel(database)
    with tempfile.TemporaryDirectory() as directory:
        for attachment_id, payload in payloads.items():
            record = _record(attachment_id, f"file-{attachment_id}.bin")
            target = Path(directory) / record["original_filename"]
            panel._start_download([(record, target)], lambda _results: None)
            thread = panel._transfer_thread
            destroyed = threading.Event()
            thread.destroyed.connect(lambda *_args, event=destroyed: event.set())
            _wait_for_transfer(panel)
            assert target.read_bytes() == payload
            assert _wait_until(destroyed.is_set)
            assert panel._transfer_worker is None
            assert not _active_attachment_jobs
            assert not _active_attachment_threads
        assert len(list(Path(directory).iterdir())) == len(payloads)
    panel.shutdown()
