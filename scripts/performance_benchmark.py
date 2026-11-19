"""Controlled Phase 2 GUI measurements using instrumented fake data.

Run: python -m scripts.performance_benchmark
This never opens PostgreSQL or business data. Durations exercise the current
implementation's UI/data pipeline; they are used only for same-machine before/
after comparison.
"""
import json
import os
import statistics
import time
import faulthandler
import sys
import threading
import argparse
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from core.database import CLIENT_ACCOUNT_PAYMENT_FIELDS, CLIENT_ACCOUNT_SALE_FIELDS
from tests.test_base_tab_pagination import _FakeDatabase, _FakeEntity
from ui.dialogs.edit_dialogs.base_operation_dialog import BaseOperationDialog
from classes.sales_class import SalesClass
from classes.sales_item_class import SalesItemClass
from classes.import_class import ImportClass
from classes.import_item_class import ImportItemClass
from ui.tabs.base_tab import BaseTab
from ui.tabs.factures_tab import FacturesTab, FactureEditor, FacturePreviewDialog
from ui.widgets.attachments_widget import AttachmentPanel


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return 0.0
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


class EventLoopProbe:
    def __init__(self, interval_ms=10):
        self.interval_ms = interval_ms
        self.worst_ms = 0.0
        self._last = None
        self._timer = QTimer(QApplication.instance())
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._beat)

    def start(self):
        self._last = time.perf_counter()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        return self.worst_ms

    def _beat(self):
        now = time.perf_counter()
        if self._last is not None:
            gap = (now - self._last) * 1000 - self.interval_ms
            if gap > self.worst_ms:
                self.worst_ms = gap
        self._last = now


def pump(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(int(milliseconds), loop.quit)
    loop.exec()


def pump_until(predicate, timeout_ms=10000, label="operation", details=None):
    loop = QEventLoop()
    deadline = time.perf_counter() + timeout_ms / 1000
    poll = QTimer(QApplication.instance())
    poll.setInterval(5)
    satisfied = False
    expired = False
    def check():
        nonlocal satisfied, expired
        try:
            if predicate():
                satisfied = True
                loop.quit()
            elif time.perf_counter() >= deadline:
                expired = True
                print(f"[BENCH TIMEOUT] {label} at {time.monotonic():.6f}", flush=True)
                if details is not None:
                    print(f"[BENCH STATE] {details()}", flush=True)
                for thread in threading.enumerate():
                    print(f"[BENCH PYTHON THREAD] name={thread.name} ident={thread.ident}", flush=True)
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
                loop.quit()
        except Exception:
            expired = True
            loop.quit()
    poll.timeout.connect(check)
    poll.start()
    loop.exec()
    poll.stop()
    return satisfied and not expired


class MeasuredDatabase(_FakeDatabase):
    def __init__(self, latency=0.0):
        super().__init__()
        self.latency = latency
        self.calls = {}
        self.registered_classes = {"Widgets": _FakeEntity}
        self.factures = [
            {
                "id": row, "facture_number": f"FA-{row:03d}/2026", "facture_type": "normal",
                "client_name": f"Measured Client {row}", "date": "2026-10-01",
                "source_devis": f"DE-2026-{row}", "total_ttc": row * 10,
                "status": "paid" if row % 2 else "partial",
            }
            for row in range(1, 201)
        ]
        self.catalog = {
            "products": [{"id": row, "name": f"Measured Product {row}", "price": str(row), "preview_image": "", "stock": "10"} for row in range(1, 501)],
            "services": [{"id": row, "name": f"Measured Service {row}", "price": str(row), "keywords": ""} for row in range(1, 101)],
            "clients": [{"id": row, "username": f"client{row}", "name": f"Measured Client {row}", "address": "", "ice": ""} for row in range(1, 301)],
            "suppliers": [{"username": f"supplier{row}", "name": f"Measured Supplier {row}"} for row in range(1, 201)],
        }

    def _count(self, method):
        self.calls[method] = self.calls.get(method, 0) + 1
        if self.latency:
            time.sleep(self.latency)

    def connect(self, initialize_schema=False):
        self._count("connect")
        return True

    def close(self):
        self._count("close")

    def get_items(self, section, **kwargs):
        self._count("get_items")
        return [{"ID": row, "name": f"Measured {section} {row}"} for row in range(1, 102)]

    def get_operation_summary_items(self, section, **kwargs):
        self._count("get_operation_summary_items")
        return [{"ID": row, "date": "2026-10-01", "total_ht": row, "total_ttc": row * 1.2,
                 "state": "pending", "client_name": f"Measured Client {row}", "devis": f"DE-2026-{row}"}
                for row in range(1, 102)]

    def get_sale_catalog(self, *_args, **kwargs):
        self._count("get_sale_catalog")
        return self.catalog

    def list_factures(self):
        self._count("list_factures")
        return list(self.factures)

    def get_facture(self, facture_id):
        self._count("get_facture")
        return {
            **self.factures[int(facture_id) - 1], "client_id": 1, "client_username": "client1",
            "client_address": "", "client_city": "", "client_ice": "", "notes": "", "tva_rate": "20",
            "items": [{"item_type": "manual", "designation": "Measured line", "information": "",
                        "unit": "U", "quantity": "1", "unit_price": "10", "discount_percentage": "0",
                        "sort_order": 1}],
            "sources": [], "paid": "0", "remaining": str(int(facture_id) * 10), "total_ht": "10",
            "vat_amount": "2", "selected_total_ttc": "0", "previous_advance_ttc": "0",
        }

    def get_facture_payments(self, facture_id):
        self._count("get_facture_payments")
        return []

    def get_next_facture_preview(self):
        self._count("get_next_facture_preview")
        return "FA-999/2026"

    def get_client_sales(self, client_id):
        self._count("get_client_sales")
        return [{"id": row, "devis": f"DE-2026-{row}", "date": "2026-10-01", "tva": 20, "subtotal": row} for row in range(1, 6)]

    def list_attachments(self, entity_type, entity_id):
        self._count("list_attachments")
        return []

    def upload_attachment(self, entity_type, entity_id, filename, encoded, *args, **kwargs):
        self._count("upload_attachment")
        return 1

    def download_attachment(self, attachment_id):
        self._count("download_attachment")
        import base64
        from pathlib import Path
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360010000020001e221bc330000000049454e44ae426082"
        )
        return base64.b64encode(png).decode()

    def get_next_devis_preview(self):
        self._count("get_next_devis_preview")
        return "DE-2026-999"

    def save_sale_with_items(self, **kwargs):
        self._count("save_sale_with_items")
        return {"transaction": "committed", "sale_id": 999, "saved": len(kwargs.get("items", []))}

    def save_import_with_items(self, **kwargs):
        self._count("save_import_with_items")
        return {"transaction": "committed", "import_id": 999, "saved": len(kwargs.get("items", []))}

    def _normalize_exact(self, value):
        return " ".join(str(value or "").split()).casefold()


class MeasuredRemoteDatabase(MeasuredDatabase):
    def __init__(self, latency=0.0):
        super().__init__(latency)
        self.offline = False


    def _rpc(self, method, result):
        self._count(f"rpc:{method}")
        if self.latency:
            time.sleep(self.latency)
        return result

    def get_items(self, section, **kwargs):
        return self._rpc("get_items", super().get_items(section, **kwargs))

    def get_operation_summary_items(self, section, **kwargs):
        return self._rpc("get_operation_summary_items", super().get_operation_summary_items(section, **kwargs))

    def get_sale_catalog(self, *args, **kwargs):
        return self._rpc("get_sale_catalog", super().get_sale_catalog(*args, **kwargs))

    def list_factures(self):
        return self._rpc("list_factures", super().list_factures())

    def get_facture(self, facture_id):
        return self._rpc("get_facture", super().get_facture(facture_id))

    def get_facture_payments(self, facture_id):
        return self._rpc("get_facture_payments", super().get_facture_payments(facture_id))

    def get_next_facture_preview(self):
        return self._rpc("get_next_facture_preview", super().get_next_facture_preview())

    def get_client_sales(self, client_id):
        return self._rpc("get_client_sales", super().get_client_sales(client_id))

    def list_attachments(self, entity_type, entity_id):
        return self._rpc("list_attachments", super().list_attachments(entity_type, entity_id))

    def upload_attachment(self, *args, **kwargs):
        return self._rpc("upload_attachment", super().upload_attachment(*args, **kwargs))

    def download_attachment(self, attachment_id):
        return self._rpc("download_attachment", super().download_attachment(attachment_id))

    def get_next_devis_preview(self):
        return self._rpc("get_next_devis_preview", super().get_next_devis_preview())

    def save_sale_with_items(self, **kwargs):
        return self._rpc("save_sale_with_items", super().save_sale_with_items(**kwargs))

    def save_import_with_items(self, **kwargs):
        return self._rpc("save_import_with_items", super().save_import_with_items(**kwargs))


MeasuredRemoteDatabase.__name__ = "RemoteDatabase"


def measure(name, action, iterations=5, settle_ms=30, async_operation=False):
    durations = []
    stalls = []
    for _ in range(iterations):
        pump(settle_ms)
        probe = EventLoopProbe()
        probe.start()
        started = time.perf_counter()
        action()
        duration = (time.perf_counter() - started) * 1000
        stall = probe.stop()
        durations.append(duration)
        stalls.append(stall)
    return {
        "completion_median_ms": round(statistics.median(durations), 2),
        "completion_p95_ms": round(percentile(durations, .95), 2),
        "gui_blocking_fallback_ms": 0 if async_operation else round(max(durations), 2),
        "max_gui_gap_ms": round(max(stalls), 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--factures-only", action="store_true")
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    local = MeasuredDatabase()
    remote = MeasuredRemoteDatabase(latency=0.03)
    results = {}
    print("[BENCH] tab", flush=True)

    tab = BaseTab(_FakeEntity, None, local)
    results["initial_tab_fetch_start_ms"] = measure("tab", lambda: tab.refresh_table(force=True), 3)
    pump_until(lambda: not tab._refreshing, 5000)
    results["tab_worker_complete_ms"] = measure("tab-complete", lambda: pump_until(lambda: not tab._refreshing, 5000), 3)
    tab.refresh_table()
    results["tab_switch_cached_ms"] = measure("cached-tab", lambda: tab.refresh_table(), 5)
    tab.close()

    print("[BENCH] factures", flush=True)
    def facture_tab_open(db):
        print(f"[BENCH FACTURES] construct start {time.monotonic():.6f}", flush=True)
        tab = FacturesTab(db)
        print(f"[BENCH FACTURES] construct end {time.monotonic():.6f}", flush=True)
        if not pump_until(
            lambda: tab._refresh_thread is None,
            5000,
            "factures initial refresh",
            lambda: f"thread={tab._refresh_thread} running={tab._refresh_thread.isRunning() if tab._refresh_thread else None}",
        ):
            raise RuntimeError("Factures initial refresh timed out")
        tab.close()

    print(f"[BENCH FACTURES] local construct start {time.monotonic():.6f}", flush=True)
    facts_local = FacturesTab(local)
    print(f"[BENCH FACTURES] local construct end {time.monotonic():.6f}", flush=True)
    if not pump_until(lambda: facts_local._refresh_thread is None, 5000, "factures local startup"):
        raise RuntimeError("Factures initial refresh timed out")
    results["factures_init_local_ms"] = measure(
        "factures-init-local", lambda: facture_tab_open(local), 3, async_operation=True,
    )
    facts_local.close()
    facts_remote = FacturesTab(remote)
    if not pump_until(lambda: facts_remote._refresh_thread is None, 5000, "factures remote startup"):
        raise RuntimeError("Factures initial refresh timed out")
    results["factures_init_remote_ms"] = measure(
        "factures-init-remote", lambda: facture_tab_open(remote), 3, async_operation=True,
    )
    facts_remote.close()
    facts = FacturesTab(local)
    if not pump_until(lambda: facts._refresh_thread is None, 5000, "factures refresh startup"):
        raise RuntimeError("Factures initial refresh timed out")
    results["factures_refresh_local_ms"] = measure(
        "factures-refresh-local",
        lambda: (facts.refresh(), pump_until(lambda: facts._refresh_thread is None, 5000, "factures refresh")),
        5, async_operation=True,
    )
    facts.close()

    if args.factures_only:
        print(json.dumps({
            "environment": {"remote_latency_per_rpc_ms": 30, "gui_platform": os.getenv("QT_QPA_PLATFORM")},
            "results": results,
            "call_counts": {"local": local.calls, "remote": remote.calls},
        }, indent=2))
        return results

    results["facture_editor_new_local_ms"] = measure("facture-editor-local", lambda: FactureEditor(local).close(), 5)
    results["facture_editor_new_remote_ms"] = measure("facture-editor-remote", lambda: FactureEditor(remote).close(), 5)

    def preview_dialog():
        images, _geometry = __import__("ui.facture_document", fromlist=["render_facture_preview_pages"]).render_facture_preview_pages(
            local.get_facture(1), [], None
        )
        dialog = FacturePreviewDialog(images)
        dialog.update_page()
        dialog.close()
    results["facture_preview_open_ms"] = measure("facture-preview", preview_dialog, 5)

    print("[BENCH] sale dialog", flush=True)
    local_operations = MeasuredRemoteDatabase()

    def sale_dialog(db):
        print(f"[BENCH] sale class={db.__class__.__name__}", flush=True)
        dialog = BaseOperationDialog(SalesClass, SalesItemClass, database=db)
        print("[BENCH] sale waiting", flush=True)
        loaded = pump_until(lambda: dialog.isEnabled(), 3000)
        print(f"[BENCH] sale loaded={loaded}", flush=True)
        return dialog
    dialog = sale_dialog(local_operations)
    results["new_sale_open_local_total_ms"] = measure("new-sale-local", lambda: sale_dialog(local_operations).close(), 3)
    dialog.close()
    dialog_remote = sale_dialog(remote)
    results["new_sale_open_remote_total_ms"] = measure("new-sale-remote", lambda: sale_dialog(remote).close(), 3)
    dialog_remote.close()

    print("[BENCH] attachments", flush=True)
    # These methods are intentionally invoked directly because they are the
    # remaining GUI-thread transfer path; panel opening is already async.
    local_attachment = SimpleNamespace(
        database=local_operations,
        entity_type="client",
        entity_id=1,
        sale_selector=SimpleNamespace(currentData=lambda: None),
    )
    remote_attachment = SimpleNamespace(
        database=remote,
        entity_type="client",
        entity_id=1,
        sale_selector=SimpleNamespace(currentData=lambda: None),
    )
    data = b"x" * (2 * 1024 * 1024)
    results["attachment_upload_2mb_local_ms"] = measure(
        "attachment-upload-local",
        lambda: AttachmentPanel._upload_bytes(local_attachment, "measured.pdf", data),
        3,
    )
    results["attachment_upload_2mb_remote_ms"] = measure(
        "attachment-upload-remote",
        lambda: AttachmentPanel._upload_bytes(remote_attachment, "measured.pdf", data),
        3,
    )

    results["attachment_download_2mb_remote_ms"] = measure(
        "attachment-download-remote",
        lambda: AttachmentPanel._bytes(remote_attachment, {"id": 1}),
        5,
    )

    print(json.dumps({
        "environment": {"remote_latency_per_rpc_ms": 30, "gui_platform": os.getenv("QT_QPA_PLATFORM")},
        "results": results,
        "call_counts": {"local": local.calls, "remote": remote.calls},
    }, indent=2))
    return results


if __name__ == "__main__":
    main()
