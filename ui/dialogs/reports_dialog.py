"""
Reports Dialog - For selecting report type and generating PDF reports
"""
import os
import sys
import glob
import socket
import subprocess
import tempfile
import shutil
import html
from pathlib import Path
from datetime import datetime, timedelta
import shiboken6
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QMessageBox, QApplication)
from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from ui.widgets.themed_widgets import BlueButton, RedButton
from core.runtime_paths import resource_path, local_reports_dir, safe_windows_component, user_data_root
from core import diagnostics
from core.company_branding import (
    COMPANY_ADDRESS,
    COMPANY_EMAIL,
    COMPANY_LOGO_PATH,
    COMPANY_PHONE,
    build_report_footer,
    get_company_logo_block,
    resolve_company_name,
)
from decimal import Decimal, InvalidOperation
import traceback
import time
import logging

logger = logging.getLogger(__name__)

class _PdfRenderWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    cancelled = Signal(float)
    status_updated = Signal(str)

    def __init__(self, renderer, report_generator, report_type, sales_db=None):
        super().__init__()
        self.renderer = renderer
        self.report_generator = report_generator
        self.report_type = report_type
        self.sales_db = sales_db

    @Slot()
    def run(self):
        started = time.perf_counter()
        is_success = False
        is_cancelled = False
        error_msg = ""
        result = None
        worker_db = None
        try:
            if QThread.currentThread().isInterruptionRequested():
                is_cancelled = True
                return

            # A psycopg2 connection is not thread-safe: the shared
            # sales_obj.database is owned by the GUI thread and must never be
            # used from this worker. For local/host databases we open a
            # dedicated connection on this thread so report queries never
            # interleave with GUI-thread queries on the same socket.
            sales_db = self.sales_db
            if sales_db is not None and sales_db.__class__.__name__ != 'RemoteDatabase':
                try:
                    from core.database import Database
                    worker_db = Database(sales_db.profile_manager)
                    worker_db.language = getattr(sales_db, 'language', 'en')
                    worker_db.registered_classes = sales_db.registered_classes
                    if not worker_db.connect():
                        worker_db = None
                except Exception:
                    worker_db = None

            self.status_updated.emit("Preparing report data...")
            with diagnostics.operation("pdf_prepare", type=self.report_type):
                if worker_db is not None:
                    html_content, output_path = self.report_generator(self.report_type, worker_db)
                else:
                    html_content, output_path = self.report_generator(self.report_type)
            
            if QThread.currentThread().isInterruptionRequested():
                is_cancelled = True
                return
                
            self.status_updated.emit("Rendering PDF...")
            with diagnostics.operation("pdf_render", output=output_path):
                result = self.renderer(html_content, output_path)
                
                if QThread.currentThread().isInterruptionRequested():
                    is_cancelled = True
                    return
                    
                is_success = True
        except Exception as error:
            logger.exception("PDF generation failed type=%s", self.report_type)
            error_msg = str(error) or "Unknown error"
        finally:
            if worker_db is not None:
                try:
                    worker_db.close()
                except Exception:
                    pass
            if is_cancelled:
                self.cancelled.emit(started)
            elif is_success:
                self.finished.emit(result)
            else:
                self.failed.emit(error_msg)
            elapsed = time.perf_counter() - started
            logger.log(
                logging.WARNING if elapsed >= 0.5 else logging.INFO,
                "generate_sales_report completed in %.3f seconds", elapsed,
            )
            print(
                "[PERFORMANCE] generate_sales_report completed in "
                f"{elapsed:.2f} seconds"
            )


class ReportsDialog(QDialog):
    """Dialog for selecting and generating reports"""
    
    def __init__(self, sales_obj, profile_manager, parent=None):
        super().__init__(parent)
        self.sales_obj = sales_obj
        self.profile_manager = profile_manager
        self.setWindowTitle("Generate Report")
        self.setModal(True)
        self.resize(400, 200)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("Select Report Type")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Sales info
        if self.sales_obj:
            client_name = self.sales_obj.get_value('client_name') or 'Unknown Client'
            date = self.sales_obj.get_value('date') or 'Unknown Date'
            info_label = QLabel(f"Client: {client_name}\nDate: {date}")
            info_label.setStyleSheet("color: #cccccc; text-align: center;")
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)
        
        # Report type buttons
        buttons_layout = QHBoxLayout()
        self.devis_btn = BlueButton("Devis")
        self.devis_btn.clicked.connect(lambda: self.generate_report("devis"))
        buttons_layout.addWidget(self.devis_btn)

        self.bdl_btn = BlueButton("Bon de livraison")
        self.bdl_btn.clicked.connect(lambda: self.generate_report("bdl"))
        buttons_layout.addWidget(self.bdl_btn)
        
        layout.addLayout(buttons_layout)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        # Cancel button
        cancel_layout = QHBoxLayout()
        cancel_layout.addStretch()
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        cancel_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(cancel_layout)
        
        # Apply dark theme
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
    
    def generate_report(self, report_type):
        """Generate report of specified type"""
        existing_thread = getattr(self, "_report_thread", None)
        is_running = False

        if existing_thread is not None:

            try:

                if shiboken6.isValid(existing_thread) and existing_thread.isRunning():

                    is_running = True

            except RuntimeError:

                pass

        if is_running:
            return False
            
        try:
            # Disable buttons during generation
            self.devis_btn.setEnabled(False)
            self.bdl_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            
            self.status_label.setText("Starting report generation...")
            self._active_report_type = report_type
            
            thread = QThread()
            worker = _PdfRenderWorker(
                self._html_to_pdf,
                self._prepare_report,
                report_type,
                sales_db=getattr(getattr(self, 'sales_obj', None), 'database', None),
            )
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            
            # Connect to QObject-bound slots so PySide queues every widget and
            # QMessageBox operation onto the GUI thread. A lambda here can run
            # in the worker thread and make the success dialog unresponsive.
            worker.finished.connect(self._report_rendered_on_ui)
            worker.failed.connect(self._report_failed_on_ui)
            worker.status_updated.connect(self.status_label.setText)
            
            worker.finished.connect(thread.quit)
            worker.failed.connect(thread.quit)
            worker.cancelled.connect(thread.quit)
            
            worker.finished.connect(worker.deleteLater)
            worker.failed.connect(worker.deleteLater)
            worker.cancelled.connect(worker.deleteLater)
            
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(self._on_report_thread_finished)
            
            self._report_thread = thread
            self._report_worker = worker
            diagnostics.worker_started("pdf_render", "reports", report_type)
            thread.start()
            return True
        except Exception as e:
            logger.exception("Report preparation failed type=%s", report_type)
            self._report_failed(report_type, str(e))
            return False

    @Slot(str)
    def _report_rendered_on_ui(self, pdf_path):
        diagnostics.worker_finished("pdf_render", "reports", getattr(self, "_active_report_type", "report"))
        self._report_rendered(
            getattr(self, "_active_report_type", "report"), pdf_path
        )

    @Slot(str)
    def _report_failed_on_ui(self, error):
        diagnostics.worker_failed("pdf_render", "reports", getattr(self, "_active_report_type", "report"))
        self._report_failed(
            getattr(self, "_active_report_type", "report"), error
        )

    def _set_report_buttons_enabled(self, enabled):
        self.devis_btn.setEnabled(enabled)
        self.bdl_btn.setEnabled(enabled)
        self.cancel_btn.setEnabled(enabled)

    def _report_rendered(self, report_type, pdf_path):
        self._set_report_buttons_enabled(True)
        self.status_label.setText("")
        self._write_report_log(self._report_context(report_type, pdf_path, None))
        QMessageBox.information(
            self, "Success", f"Report generated successfully!\n\nSaved to: {pdf_path}"
        )
        try:
            self.open_pdf(pdf_path)
        except Exception as error:
            logger.exception("Generated report could not be opened path=%s", pdf_path)
            QMessageBox.warning(
                self, "Warning", f"Report generated but failed to open:\n{error}"
            )

    def _report_failed(self, report_type, error):
        self._set_report_buttons_enabled(True)
        self.status_label.setText("")
        details = self._report_context(
            report_type, getattr(self, "_last_output_path", None), error
        )
        self._write_report_log(details)
        QMessageBox.critical(self, "Report Error", details)

    @Slot()
    def _on_report_thread_finished(self):
        self._report_thread = None
        self._report_worker = None

    def _wait_for_report_thread(self, timeout_ms=5000):
        thread = getattr(self, "_report_thread", None)
        if thread is None:

            return True

        try:

            if not shiboken6.isValid(thread) or not thread.isRunning():
                self._report_thread = None
                self._report_worker = None
                return True

        except RuntimeError:
            # If it's deleted during the checks, it's already finished.
            self._report_thread = None
            self._report_worker = None
            return True
            
        if thread == QThread.currentThread():
            return False
            
        thread.requestInterruption()
        thread.quit()
        
        if not thread.wait(timeout_ms):
            logger.error("Report generation thread did not stop timeout=%sms", timeout_ms)
            return False
            
        if getattr(self, "_report_thread", None) is thread:
            self._report_thread = None
            self._report_worker = None
            
        return True

    def closeEvent(self, event):
        thread = getattr(self, "_report_thread", None)
        if thread and thread.isRunning():
            event.ignore()
            return
        super().closeEvent(event)
    
    def _generate_report_sync(self, report_type):
        """Synchronously generate report and return PDF path"""
        html_content, filepath = self._prepare_report(report_type)
        try:
            actual_output_path = self._html_to_pdf(html_content, filepath)
        except Exception as exc:
            raise RuntimeError(self._report_context(report_type, filepath, exc)) from exc
        self._write_report_log(self._report_context(report_type, actual_output_path, None))
        return actual_output_path

    def _prepare_report(self, report_type, database=None):
        """Collect database/UI data on the GUI thread before worker rendering.
        ``database`` is the worker-owned connection when running on the worker
        thread (local/host mode); ``None`` means the shared sales connection
        (RemoteDatabase RPC or test doubles)."""
        # Get current profile path
        if database is None:
            database = getattr(self.sales_obj, 'database', None)
        profile = getattr(self.profile_manager, "selected_profile", None)
        if not profile:
            profile = getattr(database, "remote_profile", None)
        if not profile:
            raise Exception("The host did not provide report profile details")
        self._active_profile = profile
        application_username = getattr(database, 'username', None) or 'DefaultUser'
        reports_dir = local_reports_dir(application_username)
        
        # Create reports directory if it doesn't exist
        os.makedirs(reports_dir, exist_ok=True)
        
        # Clean up old reports (older than 2 days)
        self._cleanup_old_reports(reports_dir)
        
        # Generate unique filename
        report_names = {'devis': 'DEVIS', 'bdl': 'DELIVERY_NOTE', 'facture': 'INVOICE'}
        report_label = report_names.get(report_type, safe_windows_component(report_type, 'REPORT').upper())
        sales_id = self.sales_obj.get_value('id') or self.sales_obj.get_value('ID') or 0
        report_id = f"DOC-{int(sales_id):06d}" if report_type == 'devis' else str(sales_id)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        counter = 0
        while True:
            suffix = f"_{counter}" if counter else ""
            filename = f"{report_label}_{report_id}_{timestamp}{suffix}.pdf"
            filepath = os.path.join(reports_dir, filename)
            if not os.path.exists(filepath):
                break
            counter += 1
        self._last_output_path = filepath
        
        # Generate HTML content
        html_content = self._generate_html_content(report_type, database)
        
        return html_content, filepath

    def _report_context(self, report_type, path, error):
        database = getattr(self.sales_obj, 'database', None)
        mode = 'connected client' if database.__class__.__name__ == 'RemoteDatabase' else 'host/local'
        status = 'success' if error is None else 'failed'
        message = [
            f"Report operation: {status}",
            f"Report type: {report_type}",
            f"Application username: {getattr(database, 'username', None) or 'DefaultUser'}",
            f"Computer mode: {mode}",
            f"Computer name: {socket.gethostname()}",
            f"Local path: {path or 'not allocated'}",
        ]
        if error is not None:
            message.extend((f"Exception: {error}", traceback.format_exc()))
        return "\n".join(message)

    @staticmethod
    def _write_report_log(message):
        logger.info("Report operation\n%s", message)
    
    def _cleanup_old_reports(self, reports_dir):
        """Delete reports older than 48 hours"""
        cutoff_date = datetime.now() - timedelta(hours=48)
        
        for pattern in ["*.pdf"]:
            for report_file in glob.glob(os.path.join(reports_dir, pattern)):
                try:
                    file_mtime = datetime.fromtimestamp(os.path.getmtime(report_file))
                    if file_mtime < cutoff_date:
                        os.remove(report_file)
                        print(f"Cleaned up old report: {os.path.basename(report_file)}")
                except Exception as e:
                    print(f"Error deleting old report {report_file}: {e}")
    
    def _generate_html_content(self, report_type, database=None):
        """Generate HTML content based on report type"""
        # Sales Bon de Livraison reuses the Devis template verbatim (same
        # layout, columns, totals, Sections, pagination) - only the document
        # identity/title text differs (see 'document_type_label'). This is
        # the Sales-side BDL only; Import BL keeps its own separate template
        # (import_bl_templet.html via ImportBdlDialog) and numbering.
        template_filename = (
            "devis_templet.html" if report_type == "bdl" else f"{report_type}_templet.html"
        )
        template_path = resource_path("report", template_filename)
        self._log_report_resources(report_type, template_path)
        if not os.path.isfile(template_path):
            raise FileNotFoundError(f"Required report template is missing: {template_path}")
        
        # Read template
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Get sales data
        sales_data = self._extract_sales_data(report_type, database)
        
        # Replace placeholders
        html_content = self._replace_placeholders(template_content, sales_data)
        
        return html_content
    
    def _get_company_logo_block(self):
        """Return the report logo <img> block (central company_branding source)."""
        return get_company_logo_block()

    def _extract_sales_data(self, report_type: str, database=None):
        """Extract data from sales object"""
        try:
            # Worker-owned connection when generating on the worker thread
            # (local/host mode); falls back to the shared sales connection.
            db = database or getattr(self.sales_obj, 'database', None)

            def _fmt_fr(value: float) -> str:
                try:
                    s = f"{float(value):,.2f}"
                    # Convert 1,234.56 -> 1 234,56
                    return s.replace(',', ' ').replace('.', ',')
                except Exception:
                    return str(value)

            def _decimal(value) -> Decimal:
                try:
                    from core.calculations import to_decimal
                    return to_decimal(value)
                except Exception:
                    return Decimal("0")

            def _fmt_quantity(value) -> str:
                number = _decimal(value)
                return format(number.normalize(), "f") if number != number.to_integral() else str(int(number))

            # Get profile data
            profile = (
                getattr(self, "_active_profile", None)
                or getattr(self.profile_manager, "selected_profile", None)
                or getattr(
                    getattr(self.sales_obj, "database", None),
                    "remote_profile", None,
                )
            )
            if not profile:
                raise RuntimeError("Report profile details are unavailable")
            company_name = resolve_company_name(profile)
            company_phone = COMPANY_PHONE
            company_address = COMPANY_ADDRESS
            company_email = COMPANY_EMAIL
            report_footer = build_report_footer()

            logo_block = get_company_logo_block()

            # Extract sales data
            client_username = self.sales_obj.get_value('client_username') or ""
            client_name = self.sales_obj.get_value('client_name') or ""
            date = self.sales_obj.get_value('date') or datetime.now().strftime("%d-%m-%Y")
            total_price = self.sales_obj.get_value('total_price') or 0

            # Look up the client's contact details for the report customer block.
            client_address = ""
            client_phone = ""
            client_email = ""
            client_ice = ""
            client_id = self.sales_obj.get_value('client_id')
            if db is not None:
                try:
                    if client_id:
                        db.cursor.execute(
                            "SELECT address, phone, email, ice FROM Clients WHERE ID = %s", (client_id,)
                        )
                    else:
                        db.cursor.execute(
                            "SELECT address, phone, email, ice FROM Clients WHERE username = %s", (client_username,)
                        )
                    client_row = db.cursor.fetchone()
                    if client_row:
                        client_address = client_row[0] or ""
                        client_phone = client_row[1] or ""
                        client_email = client_row[2] or ""
                        client_ice = client_row[3] or ""
                except Exception as e:
                    print(f"DEBUG: Error getting client contact details: {e}")

            sale_notes = self.sales_obj.get_value('notes') or ""

            # Generate document reference. Devis and the Sales Bon de
            # Livraison both use the canonical, user-editable devis reference
            # (DE-YYYY-N) when one exists - the Sales BL is simply another
            # printed representation of the same Sale/Devis, never a second
            # persisted number. Falls back to a deterministic DOC-<id>
            # placeholder for legacy rows with no devis reference yet.
            sales_id = self.sales_obj.get_value('id') or self.sales_obj.get_value('ID') or 1
            try:
                doc_devis = str(self.sales_obj.get_value('devis') or '').strip()
            except Exception:
                doc_devis = ''
            if report_type in ('devis', 'bdl') and doc_devis:
                doc_ref = html.escape(doc_devis)
            else:
                doc_ref = f"DOC-{sales_id:06d}"
            
            # Get sales items - ensure they are loaded from database
            items_html = ""
            total_quantity = 0
            rendered_rows = 0

            # Load sales items if not already loaded
            if not hasattr(self.sales_obj, 'items') or not self.sales_obj.items:
                print("DEBUG: Loading sales items from database...")
                sales_id_value = self.sales_obj.get_value('id') or self.sales_obj.get_value('ID')
                if sales_id_value and db is not None:
                    try:
                        # Load items from database
                        items_data = db.get_items_by_operation_id(sales_id_value, 'Sales_Items')
                        print(f"DEBUG: Found {len(items_data)} sales items in database")
                        
                        # Create item objects
                        from classes.sales_item_class import SalesItemClass
                        self.sales_obj.items = []
                        for item_data in items_data:
                            item_obj = SalesItemClass(0, db)
                            # Load item data
                            for key, value in item_data.items():
                                if key in item_obj.parameters:
                                    try:
                                        item_obj.set_value(key, value)
                                    except:
                                        pass
                            self.sales_obj.items.append(item_obj)
                    except Exception as e:
                        print(f"DEBUG: Error loading sales items: {e}")
            
            if hasattr(self.sales_obj, 'items') and self.sales_obj.items:
                print(f"DEBUG: Processing {len(self.sales_obj.items)} sales items")
                total_ht = 0
                
                # Bulk prefetch missing product names
                missing_product_ids = set()
                for item in self.sales_obj.items:
                    if not item.get_value('product_name') and item.get_value('product_id'):
                        missing_product_ids.add(int(item.get_value('product_id')))
                
                prefetched_product_names = {}
                if missing_product_ids and db is not None:
                    try:
                        format_strings = ','.join(['%s'] * len(missing_product_ids))
                        db.cursor.execute(
                            f"SELECT id, name FROM Products WHERE id IN ({format_strings})", 
                            tuple(missing_product_ids)
                        )
                        for row in db.cursor.fetchall():
                            prefetched_product_names[row[0]] = row[1]
                    except Exception as e:
                        print(f"DEBUG: Error in bulk product name lookup: {e}")

                for item in self.sales_obj.items:
                    product_name = item.get_value('product_name') or ""
                    item_information = item.get_value('information') or ""
                    product_id = item.get_value('product_id') or ""
                    service_id = item.get_value('service_id') or ""
                    item_type = str(item.get_value("item_type") or "").casefold()
                    is_service = item_type == "service" or (
                        bool(service_id) and not bool(product_id)
                    )
                    
                    # If product_name is empty, try to get it from pre-fetched dictionary
                    if not product_name and product_id:
                        try:
                            pid_int = int(product_id)
                            if pid_int in prefetched_product_names:
                                product_name = prefetched_product_names[pid_int]
                        except ValueError:
                            pass
                    
                    quantity = _decimal(item.get_value('quantity'))
                    unit_price = _decimal(item.get_value('unit_price'))
                    subtotal = item.get_value('subtotal') or (quantity * unit_price)

                    print(f"DEBUG: Item - Product: {product_name}, Qty: {quantity}, Price: {unit_price}")
                    
                    total_quantity += quantity
                    total_ht += _decimal(subtotal)
                    quantity_text = _fmt_quantity(quantity)
                    
                    if report_type in ('devis', 'bdl'):
                        # The Sales Bon de Livraison is the same printed
                        # representation of the Sale as the Devis: identical
                        # columns, identical Products + Services, identical
                        # persisted item order - only the document identity
                        # (title/reference label) differs, applied via the
                        # shared template's document_type_label.
                        product_code = html.escape(str(product_id)) if product_id else "-"
                        escaped_name = html.escape(str(product_name))
                        designation_html = (
                            f'<strong class="item-name">{escaped_name}</strong>'
                            if is_service
                            else f'<span class="product-item-name">{escaped_name}</span>'
                        )
                        if item_information:
                            designation_html += (
                                f'<span class="item-detail"> {html.escape(str(item_information))}</span>'
                            )
                        row_html = (
                            f"<tr><td>{product_code}</td>"
                            f"<td>{designation_html}</td>"
                            f"<td>{quantity_text}</td>"
                            f"<td>{_fmt_fr(unit_price)}</td>"
                            f"<td>{_fmt_fr(subtotal)}</td></tr>"
                        )
                    else:
                        escaped_name = html.escape(str(product_name))
                        designation_html = (
                            f'<strong class="item-name">{escaped_name}</strong>'
                            if is_service
                            else f'<span class="product-item-name">{escaped_name}</span>'
                        )
                        if item_information:
                            designation_html += (
                                f'<span class="item-detail"> {html.escape(str(item_information))}</span>'
                            )
                        # Preserve the existing four-column facture presentation.
                        row_html = (
                            f"<tr><td>{designation_html}</td>"
                            f"<td>{quantity_text}</td>"
                            f"<td>{_fmt_fr(unit_price)}</td>"
                            f"<td>{_fmt_fr(subtotal)}</td></tr>"
                        )

                    items_html += row_html + "\n"
                    rendered_rows += 1
                # Do not add visual filler rows; they stretch the printable report table.
                try:
                    current_rows = len(self.sales_obj.items)
                    filler_needed = 0
                    filler_cols = 5 if report_type in ('devis', 'bdl') else 4
                    filler_row = (
                        '<tr class="filler">'
                        + '<td style="text-align: left">&nbsp;</td>'
                        + '<td>&nbsp;</td>' * (filler_cols - 1)
                        + '</tr>\n'
                    )
                    items_html += filler_row * filler_needed
                except Exception:
                    pass
            else:
                print("DEBUG: No sales items found")
                filler_cols = 5 if report_type in ('devis', 'bdl') else 4
                items_html = f'<tr class="empty-row"><td colspan="{filler_cols}">Aucun article</td></tr>'
                total_ht = 0
            
            # Calculate financial totals for devis using centralized function.
            # LAMIBOIS applies no VAT: the stored 'tva' value is intentionally
            # ignored, even on legacy Sales that still carry a nonzero value -
            # Net à payer = Sum(Quantity x Unit Price) - Remise.
            total_remise = _decimal(self.sales_obj.get_value('remise') or 0)

            from classes.sales_class import calculate_sale_totals
            totals = calculate_sale_totals(total_ht, total_remise, 0)
            net_ht = totals['total_ht']
            tva_amount = totals['vat_amount']
            total_ttc = totals['total_ttc']
            total_regle = Decimal("0")
            net_a_payer = total_ttc
            
            # The templates own the table structure so print engines can repeat
            # its header and paginate rows naturally.
            items_final = items_html

            # No separate BDL logic anymore
            total_qte_commandee = 0
            total_qte_livree = 0
            reste_a_livrer = 0

            return {
                'company_name': company_name,
                'company_phone': company_phone,
                'company_address': company_address,
                'company_email': company_email,
                'report_footer': report_footer.replace('\n', '<br/>'),
                'company_siret': "",  # Add if available in profile
                'company_tva': "",    # Add if available in profile
                'date': date,
                'document_type_label': (
                    'BON DE LIVRAISON N°' if report_type == 'bdl' else 'DEVIS N°'
                ),
                'document_ref': doc_ref,
                'client_name': client_name,
                'client_address': client_address,
                'client_phone': client_phone,
                'client_email': client_email,
                'client_ice': html.escape(str(client_ice)),
                'sale_notes': html.escape(str(sale_notes)).replace('\n', '<br>'),
                'payment_terms': '',
                'commercial': "Sales Team",         # Default commercial
                'items': items_final,
                'table_frame_class': 'fill-page' if rendered_rows <= 8 else '',
                # Financial fields for devis / facture
                'total_remise': _fmt_fr(total_remise),
                'total_ht': _fmt_fr(net_ht),
                'total_regle': _fmt_fr(total_regle),
                'net_a_payer': _fmt_fr(net_a_payer),
                # BDL specific pricing fields
                'tva': _fmt_fr(tva_amount),
                'total_ttc': _fmt_fr(total_ttc),
                # Logo block
                'logo_block': logo_block
            }
        except Exception as e:
            raise RuntimeError(f"Could not extract report data: {e}") from e
    
    def _replace_placeholders(self, template_content, data):
        """Replace template placeholders with actual data"""
        for key, value in data.items():
            placeholder = f"{{{{ {key} }}}}"
            template_content = template_content.replace(placeholder, str(value))
        
        return template_content
    
    def _html_to_pdf(self, html_content, output_path):
        """Convert HTML to PDF with the bundled Chromium renderer."""
        temp_html_path = None
        try:
            base_url = os.path.abspath(resource_path("report"))
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_html:
                temp_html.write(html_content)
                temp_html_path = temp_html.name
            from playwright.sync_api import sync_playwright
            executable = self._find_installed_chromium()
            if not executable:
                raise FileNotFoundError("The bundled Chromium PDF engine is missing.")
            self._write_report_log(
                f"PDF engine: Playwright Chromium\nBase path: {base_url}\n"
                f"Temporary HTML URI: {Path(temp_html_path).as_uri()}\n"
                f"Chromium: {executable}\nChromium exists: {os.path.isfile(executable)}"
            )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=executable)
                try:
                    page = browser.new_page()
                    page.emulate_media(media="print")
                    page.goto(Path(temp_html_path).as_uri(), wait_until='networkidle')
                    page.pdf(
                        path=output_path, format='A4', print_background=True,
                        prefer_css_page_size=True,
                        margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'},
                    )
                finally:
                    browser.close()
            if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
                raise RuntimeError("Chromium completed without producing a PDF.")
            return output_path
        except Exception as e:
            raise RuntimeError(f"Chromium PDF generation failed: {e}") from e
        finally:
            if temp_html_path and os.path.exists(temp_html_path):
                os.unlink(temp_html_path)

    def _log_report_resources(self, report_type, template_path):
        report_dir = resource_path('report')
        logo_path = COMPANY_LOGO_PATH
        browser_path = self._find_installed_chromium()
        self._write_report_log("\n".join([
            f"Frozen runtime: {bool(getattr(sys, 'frozen', False))}",
            f"sys._MEIPASS: {getattr(sys, '_MEIPASS', 'not set')}",
            f"Report type: {report_type}",
            f"Report base path: {report_dir}",
            f"Report base path exists: {os.path.isdir(report_dir)}",
            f"Template: {template_path}",
            f"Template exists: {os.path.isfile(template_path)}",
            "CSS: inline in template",
            f"CSS source exists: {os.path.isfile(template_path)}",
            "Fonts: Arial/Helvetica system fonts (no custom font files referenced)",
            f"Logo: {logo_path}",
            f"Logo exists: {os.path.isfile(logo_path)}",
            f"Chromium: {browser_path or 'not found'}",
            f"Chromium exists: {bool(browser_path and os.path.isfile(browser_path))}",
        ]))

    @staticmethod
    def _find_installed_chromium():
        """Find a usable Playwright/Chrome executable when revisions differ."""
        local_appdata = os.getenv('LOCALAPPDATA') or ''
        program_files = os.getenv('PROGRAMFILES') or ''
        bundled_candidates = []
        # The build cache is dot-prefixed in source mode and is copied without
        # the dot into PyInstaller's read-only resource directory.
        for bundled_browser_root in (
            resource_path('playwright-browsers'),
            resource_path('.playwright-browsers'),
        ):
            bundled_candidates.extend(glob.glob(os.path.join(
                bundled_browser_root, 'chromium_headless_shell-*',
                'chrome-headless-shell-win64', 'chrome-headless-shell.exe'
            )))
            bundled_candidates.extend(glob.glob(os.path.join(
                bundled_browser_root, 'chromium-*', 'chrome-win64', 'chrome.exe'
            )))
        bundled_existing = [path for path in bundled_candidates if os.path.isfile(path)]
        if bundled_existing:
            return max(bundled_existing, key=os.path.getmtime)

        candidates = []
        candidates.extend(glob.glob(os.path.join(
            local_appdata, 'ms-playwright', 'chromium_headless_shell-*',
            'chrome-headless-shell-win64', 'chrome-headless-shell.exe'
        )))
        candidates.extend(glob.glob(os.path.join(
            local_appdata, 'ms-playwright', 'chromium-*', 'chrome-win64', 'chrome.exe'
        )))
        candidates.extend([
            os.path.join(local_appdata, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(program_files, 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ])
        existing = [path for path in candidates if path and os.path.isfile(path)]
        return max(existing, key=os.path.getmtime) if existing else None
    

    
    def on_report_error(self, error_message):
        """Handle report generation error"""
        QApplication.restoreOverrideCursor()
        self.devis_btn.setEnabled(True)
        if hasattr(self, 'bdl_btn'):
            self.bdl_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to generate report:\n{error_message}")
    
    def open_pdf(self, pdf_path):
        """Open PDF/HTML file with default system application"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(pdf_path)
            elif os.name == 'posix':  # macOS and Linux
                subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', pdf_path])
        except Exception as e:
            raise Exception(f"Could not open file: {str(e)}")
