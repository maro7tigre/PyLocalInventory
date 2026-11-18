"""
Import Bon de Livraison dialog - generates a delivery note PDF for one import.

The selected import is printed as-is: supplier snapshot, import date, and every
delivered item. The document reference (BL-YEAR-N) is persistent - it is
allocated host-side on first print and kept stable on reprints, so reprinting
the same import always yields the same Bon de Livraison number.

Rendering runs in a QThread worker (RPC/DB data collection + Chromium PDF
render), mirroring the Sales ReportsDialog lifecycle.
"""
import base64
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QVBoxLayout)

from core.calculations import to_decimal
from core.runtime_paths import resource_path, local_reports_dir
from ui.widgets.themed_widgets import RedButton

logger = logging.getLogger(__name__)


class _ImportBdlWorker(QObject):
    """Generate the import Bon de Livraison HTML and render it to a PDF.

    Emits ``finished(path)`` or ``failed(msg)`` and ``status_updated(msg)``.
    """

    finished = Signal(str)
    failed = Signal(str)
    status_updated = Signal(str)

    def __init__(self, import_obj, profile_manager):
        super().__init__()
        self.import_obj = import_obj
        self.profile_manager = profile_manager

    @Slot()
    def run(self):
        started = time.perf_counter()
        try:
            self.status_updated.emit("Preparing Bon de Livraison data...")
            html_content, output_path = self._prepare()

            if QThread.currentThread().isInterruptionRequested():
                self.failed.emit("Report generation was cancelled.")
                return

            self.status_updated.emit("Rendering PDF...")
            self._html_to_pdf(html_content, output_path)
            self.finished.emit(output_path)
        except Exception as error:
            logger.exception("Import BDL generation failed")
            self.failed.emit(str(error) or "Unknown error")
        finally:
            elapsed = time.perf_counter() - started
            logger.info("Import BDL generation completed in %.3f seconds", elapsed)

    def _prepare(self):
        """Collect data and build the HTML; runs on the worker thread."""
        import_obj = self.import_obj
        database = getattr(import_obj, "database", None)
        if database is None:
            raise RuntimeError("The selected import has no active database connection")

        import_id = import_obj.get_value('id') or import_obj.get_value('ID') or 0
        if not import_id:
            raise RuntimeError("The selected import has no ID")
        import_id = int(import_id)

        # Persistent BL reference: allocated host-side on first print and kept
        # stable on reprints so the same import always keeps the same number.
        bl_number = str(database.get_import_bl_number(import_id) or "").strip()
        if not bl_number:
            raise RuntimeError("Could not resolve a Bon de Livraison number")

        application_username = getattr(database, 'username', None) or 'DefaultUser'
        reports_dir = local_reports_dir(application_username)
        os.makedirs(reports_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        counter = 0
        while True:
            suffix = f"_{counter}" if counter else ""
            filename = f"DELIVERY_NOTE_{import_id}_{timestamp}{suffix}.pdf"
            output_path = os.path.join(reports_dir, filename)
            if not os.path.exists(output_path):
                break
            counter += 1

        html_content = self._generate_html(import_id, bl_number)
        return html_content, output_path

    def _fmt_quantity(self, value):
        try:
            number = to_decimal(value)
            if number == number.to_integral():
                return str(int(number))
            return format(number.normalize(), "f")
        except Exception:
            return str(value)

    def _get_lamidap_logo_block(self):
        logo_path = resource_path("report", "lamidap_logo.png")
        if not os.path.isfile(logo_path):
            raise FileNotFoundError(f"Required report logo is missing: {logo_path}")
        with open(logo_path, "rb") as img_f:
            b64 = base64.b64encode(img_f.read()).decode("ascii")
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'class="report-logo" width="120" '
            f'style="width: 120px; height: auto; max-height: 80px; '
            f'object-fit: contain; display: block; margin: 0 0 6px 0;" />'
        )

    def _generate_html(self, import_id, bl_number):
        """Render the import Bon de Livraison from the selected import only."""
        import html as html_lib

        import_obj = self.import_obj
        database = getattr(import_obj, "database", None)

        template_path = resource_path("report", "import_bl_templet.html")
        if not os.path.isfile(template_path):
            raise FileNotFoundError(f"Required report template is missing: {template_path}")
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        supplier_name = import_obj.get_value('supplier_name') or import_obj.get_value('supplier_username') or "Fournisseur"
        date_value = import_obj.get_value('date') or datetime.now().strftime("%d-%m-%Y")
        notes = str(import_obj.get_value('notes') or "")

        # Supplier contact details from the Suppliers table (host-side cursor;
        # network clients fall back to the import snapshot name only).
        supplier_address = ""
        supplier_phone = ""
        supplier_email = ""
        supplier_id = import_obj.get_value('supplier_id')
        if database is not None and hasattr(database, 'cursor') and database.cursor:
            try:
                database.cursor.execute(
                    "SELECT address, phone, email FROM suppliers WHERE id = %s",
                    (int(supplier_id),) if supplier_id else (None,),
                )
                supplier_row = database.cursor.fetchone()
                if supplier_row:
                    supplier_address = supplier_row[0] or ""
                    supplier_phone = supplier_row[1] or ""
                    supplier_email = supplier_row[2] or ""
            except Exception as e:
                print(f"DEBUG: Error getting supplier contact details: {e}")

        # All delivered items with quantities.
        rows_html = ""
        rendered_rows = 0
        items = []
        if database is not None:
            try:
                items = database.get_items_by_operation_id(import_id, 'Import_Items') or []
            except Exception as e:
                print(f"DEBUG: Error loading import items: {e}")
                items = []

        for item in items:
            product_id = item.get('product_id') or ""
            product_name = item.get('product_name') or ""
            quantity = item.get('quantity') or 0
            code = html_lib.escape(str(product_id)) if product_id else "-"
            designation = f'<strong class="item-name">{html_lib.escape(str(product_name))}</strong>'
            rows_html += (
                f"<tr><td>{code}</td>"
                f"<td>{designation}</td>"
                f"<td>{self._fmt_quantity(quantity)}</td></tr>\n"
            )
            rendered_rows += 1

        if not rows_html.strip():
            rows_html = '<tr class="empty-row"><td colspan="3">Aucun article</td></tr>'

        data = {
            'logo_block': self._get_lamidap_logo_block(),
            'document_ref': html_lib.escape(str(bl_number)),
            'date': html_lib.escape(str(date_value)),
            'supplier_name': html_lib.escape(str(supplier_name)),
            'supplier_address': html_lib.escape(str(supplier_address)),
            'supplier_phone': html_lib.escape(str(supplier_phone)),
            'supplier_email': html_lib.escape(str(supplier_email)),
            'sale_notes': html_lib.escape(str(notes)).replace('\n', '<br>'),
            'items': rows_html,
            'table_frame_class': 'fill-page' if rendered_rows <= 8 else '',
        }
        for key, value in data.items():
            template = template.replace(f"{{{{ {key} }}}}", str(value))
        return template

    def _html_to_pdf(self, html_content, output_path):
        """Convert HTML to PDF with the bundled Chromium renderer."""
        temp_html_path = None
        try:
            base_url = os.path.abspath(resource_path("report"))
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as temp_html:
                temp_html.write(html_content)
                temp_html_path = temp_html.name
            from playwright.sync_api import sync_playwright
            from ui.dialogs.reports_dialog import ReportsDialog
            executable = ReportsDialog._find_installed_chromium()
            if not executable:
                raise FileNotFoundError("The bundled Chromium PDF engine is missing.")
            logger.info(
                "Import BDL PDF engine: Playwright Chromium\nBase path: %s\n"
                "Temporary HTML URI: %s",
                base_url, Path(temp_html_path).as_uri(),
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True, executable_path=executable
                )
                try:
                    page = browser.new_page()
                    page.emulate_media(media="print")
                    page.goto(Path(temp_html_path).as_uri(), wait_until="networkidle")
                    page.pdf(
                        path=output_path, format="A4", print_background=True,
                        prefer_css_page_size=True,
                        margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                    )
                finally:
                    browser.close()
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("PDF generation produced an empty or missing file.")
        except Exception as e:
            raise RuntimeError(f"Chromium PDF generation failed: {e}") from e
        finally:
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                except OSError:
                    pass


class ImportBdlDialog(QDialog):
    """Shows generation status and opens the resulting PDF."""

    def __init__(self, import_obj, profile_manager, parent=None):
        super().__init__(parent)
        self.import_obj = import_obj
        self.profile_manager = profile_manager
        self._report_thread = None
        self._report_worker = None
        self.setWindowTitle("Bon de Livraison")
        self.setModal(True)
        self.resize(420, 200)
        self.setup_ui()

        supplier_name = import_obj.get_value('supplier_name') or import_obj.get_value('supplier_username') or "Fournisseur"
        date_value = import_obj.get_value('date') or ""
        self.info_label.setText(f"Supplier: {supplier_name}\nDate: {date_value}")

        self._start_generation()

    def setup_ui(self):
        """Setup dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        title_label = QLabel("Bon de Livraison")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #cccccc; text-align: center;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)

        self.status_label = QLabel("Starting...")
        self.status_label.setStyleSheet("color: #ffffff; text-align: center;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_btn)
        layout.addLayout(buttons_layout)

        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                background-color: transparent;
            }
        """)

    def _start_generation(self):
        existing_thread = getattr(self, "_report_thread", None)
        if existing_thread is not None:
            try:
                if shiboken6.isValid(existing_thread) and existing_thread.isRunning():
                    return False
            except RuntimeError:
                pass

        self.status_label.setText("Starting generation...")
        self.cancel_btn.setEnabled(False)

        thread = QThread()
        worker = _ImportBdlWorker(self.import_obj, self.profile_manager)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(self._generation_succeeded_on_ui)
        worker.failed.connect(self._generation_failed_on_ui)
        worker.status_updated.connect(self.status_label.setText)

        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)

        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)

        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._report_thread = thread
        self._report_worker = worker
        thread.start()
        return True

    @Slot(str)
    def _generation_succeeded_on_ui(self, pdf_path):
        self.status_label.setText("")
        self.cancel_btn.setEnabled(True)
        QMessageBox.information(
            self, "Success",
            f"Bon de livraison generated successfully!\n\nSaved to: {pdf_path}",
        )
        try:
            self.open_pdf(pdf_path)
        except Exception as error:
            logger.exception("Import BDL could not be opened path=%s", pdf_path)
            QMessageBox.warning(
                self, "Warning",
                f"The Bon de livraison was generated but failed to open:\n{error}",
            )
        self.accept()

    @Slot(str)
    def _generation_failed_on_ui(self, error):
        self.status_label.setText("")
        self.cancel_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Report Error", f"Failed to generate the Bon de livraison:\n{error}"
        )
        self.accept()

    @Slot()
    def _on_thread_finished(self):
        self._report_thread = None
        self._report_worker = None

    def open_pdf(self, pdf_path):
        """Open the PDF with the default system application."""
        try:
            if os.name == 'nt':
                os.startfile(pdf_path)
            elif os.name == 'posix':
                subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', pdf_path])
        except Exception as e:
            raise Exception(f"Could not open file: {str(e)}")
