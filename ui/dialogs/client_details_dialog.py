"""Client account view with purchases, payments, and balance tracking."""

import html as html_lib
import logging
import os
import re
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from core.calculations import calculate_operation_totals, to_decimal
from core.company_branding import (
    COMPANY_ADDRESS,
    COMPANY_EMAIL,
    COMPANY_PHONE,
    build_report_footer,
    get_company_logo_block,
    resolve_company_name,
)
from core.runtime_paths import resource_path
from ui.widgets.preview_widget import PreviewWidget

logger = logging.getLogger(__name__)
_active_account_threads = set()
_active_report_threads = set()


def _format_money(value):
    return f"{float(value or 0):,.2f}".replace(",", " ")


class _SaleGroupDelegate(QStyledItemDelegate):
    """Paints a subtle separator above the first row of every new Sale group.

    Items of the same Sale keep only the normal row gridline; when the Sale
    ID changes between two rows, a slightly stronger line is drawn. This is
    purely visual - selection, scrolling and Print Selected Sale behavior are
    untouched (each row still selects/resolves its own Sale via UserRole data).
    """

    GROUP_COLOR = QColor("#4a6172")

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() != 0 or index.row() <= 0:
            return
        sale_id = index.data(Qt.UserRole + 1)
        previous = index.sibling(index.row() - 1, 0).data(Qt.UserRole + 1)
        if sale_id == previous:
            return
        painter.save()
        painter.setPen(QPen(self.GROUP_COLOR, 2))
        rect = option.rect
        painter.drawLine(rect.left(), rect.top(), rect.right(), rect.top())
        painter.restore()


class _ClientAccountWorker(QObject):
    """Fetches a client's sale-level account data off the GUI thread.

    get_client_sale_summaries() is a multi-row query (one row per Sale plus
    the payments) - for a RemoteDatabase it's a synchronous RPC round-trip,
    and even locally it can block under lock contention. Opening "View
    Client" must never freeze the window while this runs.
    """
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, database, client_id):
        super().__init__()
        self.database = database
        self.client_id = client_id

    @Slot()
    def run(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            data = self.database.get_client_sale_summaries(self.client_id)
            self.finished.emit(data)
        except Exception as e:
            logger.exception(
                "View Client account fetch failed: client_id=%s", self.client_id,
            )
            self.error.emit(str(e))


class _PaymentUpdateWorker(QObject):
    """Edits one payment's amount off the GUI thread.

    A single ``update_client_payment`` UPDATE on the remote host - never on
    the GUI thread, so a slow LAN round-trip cannot freeze the window.
    """
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, database, payment_id, amount):
        super().__init__()
        self.database = database
        self.payment_id = payment_id
        self.amount = amount

    @Slot()
    def run(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            self.database.update_client_payment(self.payment_id, self.amount)
            self.finished.emit({"payment_id": self.payment_id, "amount": self.amount})
        except Exception as e:
            logger.exception(
                "Payment amount edit failed: payment_id=%s", self.payment_id,
            )
            self.error.emit(str(e))


class _ClientReportWorker(QObject):
    """Renders a Client Statement / single-sale PDF off the GUI thread.

    Never touches QWidget/QDialog/QPrinter/QPrintPreviewDialog. It fetches the
    item-level data itself (the Sales History table never downloads Sale
    Items, so the print path pulls them on demand) and emits
    ``finished(path)`` or ``failed(msg)``.
    """
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, report_type, client_data, company_info, database,
                 client_id, selected_sale_id=None):
        super().__init__()
        self.report_type = report_type
        self.client_data = client_data
        self.company_info = company_info
        self.database = database
        self.client_id = client_id
        self.selected_sale_id = selected_sale_id
        self.currency = (company_info or {}).get("currency") or "MAD"
        self.purchases = []
        self.payments = []
        self.devis_by_sale = {}

    @Slot()
    def run(self):
        try:
            self._fetch_report_data()
            html_content = self._generate_html()
            output_dir = os.path.join(
                os.environ.get("USERPROFILE") or os.path.expanduser("~"),
                "Documents", "PyLocalInventory", "Reports",
            )
            os.makedirs(output_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            if self.report_type == "full_statement":
                filename = f"ClientStatement_{timestamp}.pdf"
            else:
                filename = f"SaleReport_{self.selected_sale_id}_{timestamp}.pdf"
            output_path = os.path.join(output_dir, filename)
            self._html_to_pdf(html_content, output_path)
            self.finished.emit(output_path)
        except Exception as e:
            logger.exception("Client report generation failed")
            self.failed.emit(str(e))

    def _fmt_money(self, value):
        """French report formatting shared by every existing PyLocalInventory report."""
        try:
            s = f"{float(value or 0):,.2f}"
            return s.replace(",", " ").replace(".", ",")
        except (TypeError, ValueError):
            return "0,00"

    def _fmt_quantity(self, value):
        number = to_decimal(value)
        if number == number.to_integral():
            return str(int(number))
        return format(number.normalize(), "f")

    def _fetch_report_data(self):
        """Pull the item-level data this report needs (on demand, never for
        the Sales History table).

        Sale-level payments and the per-Sale Devis reference are loaded with
        the items so every report renders fresh data with stable references.
        """
        if self.report_type == "selected_sale":
            data = self.database.get_client_sale_items(self.selected_sale_id)
            self.purchases = data.get("purchases") or []
            self.payments = data.get("payments") or []
            self.devis_by_sale = {
                s["sale_id"]: s.get("devis") for s in (data.get("sales") or [])
            }
        else:
            account = self.database.get_client_account(self.client_id)
            self.purchases = account.get("purchases") or []
            self.payments = account.get("payments") or []
            summaries = self.database.get_client_sale_summaries(self.client_id)
            self.devis_by_sale = {
                s["sale_id"]: s.get("devis") for s in (summaries.get("sales") or [])
            }

    def _html_to_pdf(self, html_content, output_path):
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
        finally:
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                except OSError:
                    pass

    def _get_company_logo_block(self):
        return get_company_logo_block()

    _STATE_LABELS = {
        "pending": "En attente",
        "paid": "Payé",
        "sold": "Soldé",
        "cancelled": "Annulé",
        "canceled": "Annulé",
        "draft": "Brouillon",
        "historical": "Historique",
    }

    @classmethod
    def _format_french_date(cls, value):
        """Normalise a stored date (YYYY-MM-DD, DD-MM-YYYY or DD/MM/YYYY)
        to the French display form DD/MM/YYYY. Unparseable values pass through."""
        raw = str(value or "").strip()
        if not raw:
            return ""
        parts = re.split(r"[/-]", raw)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            a, b, c = parts
            if len(a) == 4:  # YYYY-MM-DD
                year, month, day = a, b, c
            else:            # DD-MM-YYYY
                day, month, year = a, b, c
            if len(day) <= 2 and len(month) <= 2 and len(year) == 4:
                return f"{int(day):02d}/{int(month):02d}/{year}"
        return raw

    @classmethod
    def _state_label(cls, value):
        key = str(value or "").strip().lower()
        return cls._STATE_LABELS.get(key, key.replace("_", " ").title() or "—")

    def _generate_html(self):
        template_path = resource_path("report", "client_statement_templet.html")
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        currency = self.currency

        # ------------------------------------------------------------------
        # Document header (right pane): title + generation date.
        # ------------------------------------------------------------------
        if self.report_type == "selected_sale":
            document_title = "Détail de Vente"
        else:
            document_title = "Relevé de Compte Client"
        document_date = time.strftime("%d/%m/%Y")

        # ------------------------------------------------------------------
        # Client block - customer-facing fields only, never the internal ID.
        # ------------------------------------------------------------------
        client_name = html_lib.escape(
            str(
                self.client_data.get("name")
                or self.client_data.get("username")
                or "Client"
            )
        )
        client_fields = []
        for label, key in (
            ("Type", "client_type"),
            ("ICE", "ice"),
            ("Tél", "phone"),
            ("Email", "email"),
            ("Adresse", "address"),
        ):
            value = str(self.client_data.get(key) or "").strip()
            if value and value not in ("-", "None"):
                client_fields.append(
                    f'<div class="field"><strong>{html_lib.escape(label)} :</strong> '
                    f"{html_lib.escape(value)}</div>"
                )
        client_block = (
            '<div class="client-caption">Client</div>'
            f'<div class="client-name">{client_name}</div>'
        )
        if client_fields:
            client_block += '<div class="client-lines">' + "".join(client_fields) + "</div>"

        # ------------------------------------------------------------------
        # Group the canonical purchase rows by Sale and compute each Sale's
        # authoritative financial block (same formulas as the Client Account
        # dialog: one raw/remise/vat pass per Sale, TTC never double-counted).
        # ------------------------------------------------------------------
        if self.report_type == "selected_sale":
            filtered = [
                p for p in self.purchases
                if p.get("sale_id") == self.selected_sale_id
            ]
        else:
            filtered = list(self.purchases)

        sales = {}
        for purchase in filtered:
            try:
                sale_id = int(purchase["sale_id"])
            except (TypeError, ValueError):
                sale_id = purchase["sale_id"]
            sales.setdefault(sale_id, []).append(purchase)

        sale_blocks = []
        self.sale_ttc_by_id = {}
        self.sale_paid_by_id = {}
        for sale_id in sorted(
            sales,
            key=lambda s: int(s)
            if isinstance(s, (int, float, str)) and str(s).isdigit()
            else 0,
        ):
            rows = sales[sale_id]
            sale_blocks.append(self._render_sale_section(sale_id, rows, currency))

        sales_content = "".join(sale_blocks)

        total_sales = sum(self.sale_ttc_by_id.values(), Decimal("0"))
        total_paid = sum(self.sale_paid_by_id.values(), Decimal("0"))
        total_remaining = max(total_sales - total_paid, Decimal("0"))

        # ------------------------------------------------------------------
        # Global account summary (top of the statement).
        # ------------------------------------------------------------------
        if self.report_type == "full_statement":
            global_summary = (
                '<div class="cell"><span class="label">Total des ventes</span>'
                f'<span class="value">{self._fmt_money(total_sales)} {currency}</span></div>'
                '<div class="cell"><span class="label">Total payé</span>'
                f'<span class="value">{self._fmt_money(total_paid)} {currency}</span></div>'
                '<div class="cell due"><span class="label">Solde restant</span>'
                f'<span class="value">{self._fmt_money(total_remaining)} {currency}</span></div>'
            )
        else:
            global_summary = ""

        # ------------------------------------------------------------------
        # Small repeated summary at the end (full statement only).
        # ------------------------------------------------------------------
        if self.report_type == "full_statement":
            final_summary = (
                '<div class="final-summary"><table class="totals-table">'
                f"<tr><th>Total des ventes</th><td>{self._fmt_money(total_sales)} {currency}</td></tr>"
                f"<tr><th>Total payé</th><td>{self._fmt_money(total_paid)} {currency}</td></tr>"
                f'<tr class="grand-total"><th>Solde restant</th>'
                f"<td>{self._fmt_money(total_remaining)} {currency}</td></tr>"
                "</table></div>"
            )
        else:
            final_summary = ""

        report_footer = build_report_footer()
        if report_footer:
            report_footer = html_lib.escape(str(report_footer)).replace("\n", "<br>")

        company_name = resolve_company_name(self.company_info)
        company_address = html_lib.escape(COMPANY_ADDRESS)
        company_phone = html_lib.escape(COMPANY_PHONE)
        company_email = html_lib.escape(COMPANY_EMAIL)

        data = {
            "logo_block": self._get_company_logo_block(),
            "company_name": html_lib.escape(str(company_name)),
            "company_address": company_address,
            "company_phone": company_phone,
            "company_email": company_email,
            "document_title": document_title,
            "document_date": document_date,
            "client_block": client_block,
            "global_summary": global_summary,
            "sales_content": sales_content,
            "final_summary": final_summary,
            "report_footer": report_footer,
        }

        # Match ReportsDialog._replace_placeholders: '{{ key }}' with spaces.
        for key, value in data.items():
            template = template.replace(f"{{{{ {key} }}}}", str(value))

        if "{{" in template:
            raise RuntimeError("Report template placeholders were left unfilled")
        return template

    def _sale_paid(self, rows):
        """Authoritative per-Sale Paid value (sum of this Sale's payments,
        capped at the sale total by the caller)."""
        sale_id = rows[0]["sale_id"]
        return sum(
            (
                to_decimal(pay.get("amount") or 0)
                for pay in self.payments
                if self._payment_belongs_to(pay, sale_id)
            ),
            Decimal("0"),
        )

    def _render_sale_section(self, sale_id, rows, currency):
        """Build the HTML of one complete Sale section: header (with the Devis
        reference), items table, financial block and payment history."""
        first = rows[0]
        raw = sum(
            (to_decimal(r.get("quantity") or 0) * to_decimal(r.get("unit_price") or 0))
            for r in rows
        )
        remise = to_decimal(first.get("remise") or 0)
        totals = calculate_operation_totals(raw, remise)
        total = totals["total"]
        paid = min(self._sale_paid(rows), total)
        remaining = max(total - paid, Decimal("0"))

        sale_date = self._format_french_date(first.get("date") or "")
        devis = (self.devis_by_sale or {}).get(sale_id) or ""
        if devis:
            devis_html = (
                f'<span class="devis-badge">DEVIS N° {html_lib.escape(devis)}</span>'
            )
        else:
            devis_html = ""

        header = (
            '<div class="sale">'
            '<div class="sale-header">'
            f'<div class="sale-title">VENTE N°{sale_id}{devis_html}</div>'
            f'<div class="sale-meta"><strong>Date :</strong> {html_lib.escape(sale_date)}</div>'
            "</div>"
            '<div class="sale-subtitle">Articles / Services</div>'
            '<table class="items-table">'
            "<thead><tr><th>Désignation</th><th>Information</th>"
            "<th>Qté</th><th>P.U</th><th>Total</th></tr></thead><tbody>"
        )

        item_rows = []
        for item in rows:
            qty = to_decimal(item.get("quantity") or 0)
            price = to_decimal(item.get("unit_price") or 0)
            subtotal = qty * price
            name = html_lib.escape(str(item.get("product") or ""))
            info = str(item.get("information") or "").strip()
            item_rows.append(
                f'<tr><td class="item-name">{name}</td>'
                f"<td>{html_lib.escape(info) if info else '—'}</td>"
                f"<td>{self._fmt_quantity(qty)}</td>"
                f"<td>{self._fmt_money(price)}</td>"
                f"<td>{self._fmt_money(subtotal)}</td></tr>"
            )
        items_html = "".join(item_rows)
        items_footer = "</tbody></table>"

        totals_html = (
            '<table class="totals-table">'
            f"<tr><th>Sous-total</th><td>{self._fmt_money(raw)} {currency}</td></tr>"
            f"<tr><th>Remise</th><td>{self._fmt_money(totals['remise'])} {currency}</td></tr>"
            f'<tr class="grand-total"><th>Total</th><td>{self._fmt_money(total)} {currency}</td></tr>'
            f'<tr class="paid"><th>Total payé</th><td>{self._fmt_money(paid)} {currency}</td></tr>'
            f'<tr class="due"><th>Reste à payer</th><td>{self._fmt_money(remaining)} {currency}</td></tr>'
            "</table>"
        )

        # Payment history of this Sale only, in real chronology, with the
        # running balance after each payment.
        sale_payments = [
            pay for pay in self.payments
            if self._payment_belongs_to(pay, sale_id)
        ]
        sale_payments.sort(key=self._payment_sort_key)
        balance = total
        payment_rows_html = []
        for pay in sale_payments:
            amount = to_decimal(pay.get("amount") or 0)
            balance = max(balance - amount, Decimal("0"))
            payment_rows_html.append(
                f"<tr><td>{html_lib.escape(self._format_french_date(pay.get('date')))}</td>"
                f"<td>{self._fmt_money(amount)} {currency}</td>"
                f"<td>{self._fmt_money(balance)} {currency}</td></tr>"
            )
        payments_paid = sum(
            (to_decimal(pay.get("amount") or 0) for pay in sale_payments),
            Decimal("0"),
        )
        payments_paid = min(payments_paid, total)
        payments_remaining = max(total - payments_paid, Decimal("0"))

        if payment_rows_html:
            payments_html = (
                '<table class="payments-table">'
                "<thead><tr><th>Date</th><th>Montant payé</th>"
                "<th>Solde après paiement</th></tr></thead><tbody>"
                + "".join(payment_rows_html)
                + "</tbody></table>"
            )
        else:
            payments_html = (
                '<div class="no-payments">Aucun paiement enregistré pour cette vente.</div>'
            )

        payments_summary = (
            f'<div class="payments-summary">Total payé : <strong>{self._fmt_money(payments_paid)} {currency}</strong>'
            f"&nbsp;&nbsp;&nbsp;"
            f"Reste à payer : <strong>{self._fmt_money(payments_remaining)} {currency}</strong></div>"
        )

        bottom = (
            '<div class="sale-bottom">'
            f'<section class="totals-panel">{totals_html}</section>'
            '<section class="payments-panel">'
            '<div class="section-label">Historique des paiements</div>'
            f"{payments_html}{payments_summary}"
            "</section></div>"
        )

        self.sale_ttc_by_id[sale_id] = total
        self.sale_paid_by_id[sale_id] = paid
        return header + items_html + items_footer + bottom + "</div>"

    def _payment_belongs_to(self, pay, sale_id):
        try:
            return int(pay.get("sale_id")) == int(sale_id)
        except (TypeError, ValueError):
            return str(pay.get("sale_id")) == str(sale_id)

    def _payment_sort_key(self, pay):
        """Chronological order: parsed date first, then insertion id so that
        same-day entries keep their recorded order."""
        try:
            parts = re.split(r"[/-]", str(pay.get("date") or "").strip())
            parts = [p.strip() for p in parts if p.strip()]
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                a, b, c = parts
                year, month, day = (a, b, c) if len(a) == 4 else (c, b, a)
                return (int(year), int(month), int(day), int(pay.get("payment_id") or 0))
        except (TypeError, ValueError):
            pass
        return (9999, 0, 0, int(pay.get("payment_id") or 0))


class _EditPaymentDialog(QDialog):
    """Small modal dialog that edits one payment's amount.

    Only the amount is changed - a single ``update_client_payment`` UPDATE.
    The no-overpayment rule is enforced here (and again server-side): the new
    amount cannot take the sale's paid total past its Total TTC.
    """

    def __init__(self, parent, payment_id, sale_id, devis, current, max_allowed,
                 currency="MAD"):
        super().__init__(parent)
        self.payment_id = payment_id
        self.sale_id = sale_id
        self.max_allowed = max_allowed
        self.currency = currency

        self.setWindowTitle("Edit Payment Amount")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info = QLabel(
            f"Payment #{payment_id} — Sale #{sale_id} (Devis {devis or '-'})\n"
            f"Current amount: {_format_money(current)} {currency}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.amount_edit = QLineEdit()
        self.amount_edit.setText(f"{float(current):.2f}")
        self.amount_edit.setPlaceholderText("e.g. 1500.00")
        form.addRow("New amount:", self.amount_edit)
        layout.addLayout(form)

        hint = QLabel(
            f"Maximum allowed (so the sale is not overpaid): "
            f"{_format_money(max_allowed)} {currency}"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.save_btn = QPushButton("Save")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._validate_and_accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

        self.amount_edit.returnPressed.connect(self._validate_and_accept)
        self.amount_edit.setFocus()

    def _validate_and_accept(self):
        from core.calculations import parse_decimal_input, InputState
        state, amount = parse_decimal_input(self.amount_edit.text())
        if state in (InputState.INVALID, InputState.EMPTY, InputState.INTERMEDIATE):
            QMessageBox.warning(
                self,
                "Invalid Amount",
                "Enter the amount manually using numbers, for example 1500 or 1500.50.",
            )
            self.amount_edit.setFocus()
            return
        if amount <= 0 or amount > self.max_allowed + Decimal("0.001"):
            QMessageBox.warning(
                self,
                "Invalid Amount",
                f"Enter an amount between 0.01 and "
                f"{_format_money(self.max_allowed)} {self.currency}.",
            )
            self.amount_edit.setFocus()
            return
        self._amount = amount
        self.accept()

    def amount_decimal(self):
        return self._amount


class ClientDetailsDialog(QDialog):
    """Show a client's account and record payments against unpaid sales."""

    def __init__(self, client_obj, database, parent=None):
        super().__init__(parent)
        self.client_obj = client_obj
        self.database = database
        self.sales = []
        self.payments = []
        self.devis_by_sale = {}
        self.account_data = {"sales": [], "payments": []}
        self.currency = self._company_profile_values().get("currency") or "MAD"
        self._account_loaded_once = False
        self.can_record_payment = bool(
            database and getattr(database, "has_permission", lambda *_: True)("Sales", "write")
        )
        self.setWindowTitle(
            f"Client Account - {client_obj.get_value('name') or client_obj.get_value('username')}"
        )
        self.setMinimumSize(1050, 720)
        # Schema changes belong to the trusted host connection, never to a
        # read-only LAN session. Database.connect() also ensures this table.
        if database.__class__.__name__ != "RemoteDatabase":
            self._ensure_payments_table()
        self._setup_ui()
        self._account_thread = None
        self._account_worker = None
        self._report_thread = None
        self._report_worker = None
        self._payment_edit_thread = None
        self._payment_edit_worker = None
        self._payment_edit_inflight = False
        self._payment_delete_inflight = False
        self.refresh_data()

    def _ensure_payments_table(self):
        self.database.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS Payments (
                id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                sale_id INTEGER,
                sales_item_id INTEGER,
                amount DOUBLE PRECISION,
                date TEXT,
                FOREIGN KEY (sale_id) REFERENCES Sales(id) ON DELETE CASCADE,
                FOREIGN KEY (sales_item_id) REFERENCES Sales_Items(id) ON DELETE CASCADE
            )
            """
        )
        # Avoid querying information_schema through the LAN permission layer.
        # PostgreSQL can perform this migration safely and idempotently itself.
        self.database.cursor.execute(
            "ALTER TABLE Payments ADD COLUMN IF NOT EXISTS sales_item_id INTEGER"
        )
        self.database.conn.commit()

    def _setup_ui(self):
        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setMinimumWidth(980)
        root = QVBoxLayout(content)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(self.client_obj.get_value("name") or "Client")
        title.setStyleSheet("font-size:22px; font-weight:bold; color:#fff;")
        root.addWidget(title)

        # Action header: the single canonical set of account buttons.
        action_bar = QWidget()
        action_layout = QHBoxLayout(action_bar)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.print_selected_btn = QPushButton("Print Selected Sale")
        self.print_selected_btn.setToolTip(
            "Print the selected sale and all of its items and payments"
        )
        self.print_selected_btn.setEnabled(False)
        self.print_selected_btn.clicked.connect(self._print_selected_sale)

        self.print_statement_btn = QPushButton("Print Full Client Statement")
        self.print_statement_btn.setToolTip(
            "Print every sale, item and payment for this client"
        )
        self.print_statement_btn.setEnabled(False)
        self.print_statement_btn.clicked.connect(self._print_full_statement)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)

        action_layout.addWidget(self.print_selected_btn)
        action_layout.addWidget(self.print_statement_btn)
        action_layout.addStretch(1)
        action_layout.addWidget(self.close_btn)
        root.addWidget(action_bar)

        info = QFrame()
        info.setObjectName("clientInfo")
        info_container = QHBoxLayout(info)
        info_container.setContentsMargins(12, 10, 12, 10)
        info_container.setSpacing(16)

        preview = PreviewWidget(120, "individual")
        image_path = self.client_obj.get_value("preview_image")
        if image_path:
            preview.set_image_path(image_path)
        info_container.addWidget(preview, 0, Qt.AlignTop)

        info_fields = QWidget()
        info_layout = QFormLayout(info_fields)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setHorizontalSpacing(20)
        for label, key in (
            ("Client ID", "id"),
            ("Username", "username"),
            ("Client Type", "client_type"),
            ("ICE", "ice"),
            ("Phone", "phone"),
            ("Email", "email"),
            ("Address", "address"),
            ("Notes", "notes"),
        ):
            value = QLabel(str(self.client_obj.get_value(key) or "-"))
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            info_layout.addRow(f"{label}:", value)
        info_container.addWidget(info_fields, 1)
        root.addWidget(info)

        totals = QHBoxLayout()
        self.total_bought_label = self._summary_value(totals, "Total Bought")
        self.total_paid_label = self._summary_value(totals, "Total Paid")
        self.remaining_label = self._summary_value(totals, "Remaining")
        root.addLayout(totals)

        # ---------- Sales History section card ----------
        sales_card = QFrame()
        sales_card.setObjectName("sectionCard")
        sales_layout = QVBoxLayout(sales_card)
        sales_layout.setContentsMargins(14, 10, 14, 12)
        sales_layout.setSpacing(8)

        sales_header = QWidget()
        sales_header_layout = QHBoxLayout(sales_header)
        sales_header_layout.setContentsMargins(0, 0, 0, 0)
        sales_header_layout.setSpacing(8)
        sales_icon = QLabel()
        sales_icon.setPixmap(
            self._tinted_icon(QStyle.SP_FileDialogDetailedView)
        )
        sales_title = QLabel("Sales History")
        sales_title.setObjectName("sectionTitle")
        self.sales_count_label = QLabel("0 records")
        self.sales_count_label.setObjectName("countLabel")
        sales_header_layout.addWidget(sales_icon)
        sales_header_layout.addWidget(sales_title)
        sales_header_layout.addStretch(1)
        sales_header_layout.addWidget(self.sales_count_label)
        sales_layout.addWidget(sales_header)

        hint_row = QWidget()
        hint_row.setObjectName("hintRow")
        hint_layout = QHBoxLayout(hint_row)
        hint_layout.setContentsMargins(0, 0, 0, 0)
        hint_layout.setSpacing(6)
        hint_icon = QLabel()
        hint_icon.setPixmap(
            self._tinted_icon(QStyle.SP_MessageBoxInformation, size=14, color="#7e95a3")
        )
        self.sales_hint_label = QLabel(
            "Select a sale to view its details, print it, or register a payment."
            if self.can_record_payment
            else "Read-only view: client details, sales, and payments cannot be changed."
        )
        hint_layout.addWidget(hint_icon)
        hint_layout.addWidget(self.sales_hint_label)
        hint_layout.addStretch(1)
        sales_layout.addWidget(hint_row)

        self.sales_stack = QStackedWidget()
        self.purchases_table = self._create_table(
            ["Sale #", "Date", "Devis"]
        )
        self.sales_empty = self._empty_state("No sales found for this client.")
        self.sales_stack.addWidget(self.purchases_table)
        self.sales_stack.addWidget(self.sales_empty)

        p_header = self.purchases_table.horizontalHeader()
        p_header.setStretchLastSection(False)
        p_header.setMinimumSectionSize(42)
        p_header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col in (0, 1):
            p_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        p_header.setMaximumSectionSize(110)

        self.purchases_table.currentCellChanged.connect(self._purchase_selected)
        sales_card.setMinimumHeight(260)
        sales_card.setMinimumWidth(300)
        sales_layout.addWidget(self.sales_stack, 1)

        # ---------- Payment History section card ----------
        payments_card = QFrame()
        payments_card.setObjectName("sectionCard")
        payments_layout = QVBoxLayout(payments_card)
        payments_layout.setContentsMargins(14, 10, 14, 12)
        payments_layout.setSpacing(8)

        payments_header = QWidget()
        payments_header_layout = QHBoxLayout(payments_header)
        payments_header_layout.setContentsMargins(0, 0, 0, 0)
        payments_header_layout.setSpacing(8)
        payments_icon = QLabel()
        payments_icon.setPixmap(
            self._tinted_icon(QStyle.SP_FileDialogListView)
        )
        payments_title = QLabel("Payment History")
        payments_title.setObjectName("sectionTitle")
        self.payments_count_label = QLabel("0 records")
        self.payments_count_label.setObjectName("countLabel")
        payments_header_layout.addWidget(payments_icon)
        payments_header_layout.addWidget(payments_title)
        payments_header_layout.addStretch(1)
        self.edit_payment_btn = QPushButton("Edit Payment Amount")
        self.edit_payment_btn.setToolTip(
            "Edit the amount of the selected payment (only that payment's "
            "amount is changed - never the sale, items or stock)"
        )
        self.edit_payment_btn.setEnabled(False)
        self.edit_payment_btn.clicked.connect(self._edit_selected_payment)
        payments_header_layout.addWidget(self.edit_payment_btn)
        self.delete_payment_btn = QPushButton("Delete Payment")
        self.delete_payment_btn.setObjectName("dangerBtn")
        self.delete_payment_btn.setToolTip(
            "Delete the selected payment permanently"
        )
        self.delete_payment_btn.setEnabled(False)
        self.delete_payment_btn.clicked.connect(self._delete_selected_payment)
        payments_header_layout.addWidget(self.delete_payment_btn)
        payments_header_layout.addWidget(self.payments_count_label)
        payments_layout.addWidget(payments_header)

        self.payments_stack = QStackedWidget()
        self.payments_table = self._create_table(
            ["Payment #", "Sale #", "Date", "Amount", "Devis"]
        )
        self.payments_empty = self._empty_state("No payments recorded yet.")
        self.payments_stack.addWidget(self.payments_table)
        self.payments_stack.addWidget(self.payments_empty)

        pay_header = self.payments_table.horizontalHeader()
        pay_header.setStretchLastSection(False)
        pay_header.setMinimumSectionSize(42)
        pay_header.setSectionResizeMode(4, QHeaderView.Stretch)
        for col in (0, 1, 2, 3):
            pay_header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        pay_header.setMaximumSectionSize(110)

        self.payments_table.currentCellChanged.connect(self._payment_selected)

        payments_card.setMinimumHeight(260)
        payments_card.setMinimumWidth(420)
        payments_layout.addWidget(self.payments_stack, 1)

        # ---------- Splitter: Sales History ~53% / Payment History ~47% ----------
        table_splitter = QSplitter(Qt.Horizontal)
        table_splitter.addWidget(sales_card)
        table_splitter.addWidget(payments_card)
        table_splitter.setStretchFactor(0, 5)
        table_splitter.setStretchFactor(1, 4)
        table_splitter.setSizes([560, 500])
        table_splitter.setChildrenCollapsible(False)
        table_splitter.setHandleWidth(8)
        table_splitter.setMinimumHeight(300)
        root.addWidget(table_splitter, 1)

        # ---------- Payment form: compact selection summary + add payment ----------
        payment_form = QWidget()
        self.payment_form = payment_form
        form_layout = QVBoxLayout(payment_form)
        form_layout.setContentsMargins(0, 4, 0, 0)
        form_layout.setSpacing(8)

        selected_bar = QFrame()
        selected_bar.setObjectName("selectedBar")
        self.selected_bar = selected_bar
        bar_layout = QHBoxLayout(selected_bar)
        bar_layout.setContentsMargins(10, 8, 10, 8)
        bar_layout.setSpacing(14)
        self.selected_sale_label = QLabel("Selected Sale #—")
        self.selected_devis_label = QLabel("Devis: —")
        self.selected_remaining_label = QLabel("Remaining: —")
        self.selected_remaining_label.setObjectName("selectedRemaining")
        bar_layout.addWidget(self.selected_sale_label)
        bar_layout.addWidget(self.selected_devis_label)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.selected_remaining_label)

        amount_label = QLabel("Amount Paid:")
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("Type amount manually, for example 1 500.00")
        self.amount_input.setMinimumWidth(260)
        self.amount_input.setEnabled(False)

        date_label = QLabel("Operation Date:")
        self.date_input = QDateEdit(QDate.currentDate())
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd-MM-yyyy")
        self.date_input.setMinimumWidth(150)

        self.add_payment_button = QPushButton("Add Payment")
        self.add_payment_button.setToolTip(
            "Record this payment against the selected sale"
        )
        self.add_payment_button.clicked.connect(self.add_payment)
        self.amount_input.returnPressed.connect(self.add_payment)

        controls = QHBoxLayout()
        controls.addWidget(amount_label)
        controls.addWidget(self.amount_input)
        controls.addWidget(date_label)
        controls.addWidget(self.date_input)
        controls.addWidget(self.add_payment_button)
        controls.addStretch()

        form_layout.addWidget(selected_bar)
        form_layout.addLayout(controls)
        root.addWidget(payment_form)
        payment_form.setVisible(self.can_record_payment)
        self._apply_selected_bar_style(Decimal("0"), has_selection=False)

        scroll_area.setWidget(content)
        window_layout.addWidget(scroll_area)

        self.setStyleSheet(
            """
            QDialog { background:#252525; color:#eee; }
            #clientInfo { background:#2d2d2d; border:1px solid #444; border-radius:6px; }
            QLabel { color:#eee; }

            #sectionCard {
                background:#2b2b2b;
                border:1px solid #3b3b3b;
                border-radius:8px;
            }
            #sectionCard QLabel { background:transparent; }
            #sectionTitle { font-size:14px; font-weight:bold; color:#ffffff; }
            #countLabel { color:#8f9aa0; font-size:12px; }
            #hintRow QLabel { color:#7e95a3; font-size:12px; }

            QTableWidget {
                background:#252525; color:#e9e9e9;
                alternate-background-color:#2b2b2b;
                gridline-color:#373737;
                border:1px solid #3c3c3c;
                selection-background-color:#1d3a54;
                selection-color:#ffffff;
            }
            QTableWidget::item:selected {
                background:#1d3a54; color:#ffffff;
                border:1px solid #3d6f96;
            }
            QHeaderView::section {
                background:#333c42; color:#dfe7eb;
                border:none;
                border-right:1px solid #3f4a50;
                border-bottom:1px solid #3f4a50;
                padding:6px 8px;
                font-weight:bold;
            }
            QTableCornerButton::section { background:#333c42; border:none; }

            QLineEdit, QDateEdit {
                background:#333; color:#fff; border:1px solid #555;
                padding:6px; min-height:24px;
            }
            QLineEdit:focus, QDateEdit:focus { border:2px solid #2196F3; }
            QPushButton {
                background:#1565C0; color:#fff; border:none;
                border-radius:5px; padding:8px 14px;
            }
            QPushButton:hover { background:#1976D2; }
            """
        )

    def _summary_value(self, layout, title):
        block = QFrame()
        block.setObjectName("clientInfo")
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(12, 8, 12, 8)
        caption = QLabel(title)
        caption.setStyleSheet("color:#aaa; font-size:12px;")
        value = QLabel(f"0.00 {self.currency}")
        value.setStyleSheet("font-size:18px; font-weight:bold;")
        block_layout.addWidget(caption)
        block_layout.addWidget(value)
        layout.addWidget(block)
        return value

    def _create_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(42)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setHighlightSections(False)
        table.setShowGrid(True)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return table

    @staticmethod
    def _empty_state(text):
        """Centered muted message shown instead of a giant empty table."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color:#8a9499; font-size:13px; background:transparent;")
        layout.addWidget(label)
        layout.addStretch(1)
        return widget

    def _tinted_icon(self, standard_icon, size=16, color="#8fa2ad"):
        """Render a standard icon in a muted single colour (QStyle icon set)."""
        source = self.style().standardIcon(standard_icon).pixmap(size, size)
        tinted = QPixmap(size, size)
        tinted.fill(Qt.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(0, 0, size, size, QColor(color))
        painter.end()
        return tinted

    _STATUS_STYLES = {
        "pending": ("#e6b04a", "#33290f"),
        "paid": ("#7fce95", "#1c2f22"),
        "sold": ("#8fc8d8", "#16303a"),
        "cancelled": ("#d99b9b", "#331f1f"),
        "canceled": ("#d99b9b", "#331f1f"),
        "draft": ("#b9c2c7", "#2a2f31"),
        "historical": ("#c9d4d9", "#2a2f31"),
    }

    def _status_display(self, state):
        text = str(state or "").strip()
        if not text:
            return "-"
        return text.replace("_", " ").title()

    def _status_colors(self, state):
        return self._STATUS_STYLES.get(
            str(state or "").strip().lower(), ("#c9d4d9", "#2a2f31")
        )

    @staticmethod
    def _format_date(value):
        """Display dates as DD/MM/YYYY so the full date is always visible.

        Never a truncated ISO prefix (e.g. ``2026-07-...``)."""
        raw = str(value or "").strip()
        if not raw:
            return "-"
        parts = re.split(r"[/-]", raw)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            a, b, c = parts
            if len(a) == 4:  # YYYY-MM-DD
                year, month, day = a, b, c
            else:            # DD-MM-YYYY
                day, month, year = a, b, c
            if len(day) <= 2 and len(month) <= 2 and len(year) == 4:
                return f"{int(day):02d}/{int(month):02d}/{year}"
        return raw

    def _apply_selected_bar_style(self, remaining, has_selection=True):
        """Colour the selection strip accent by balance state (never relies on
        colour alone - every label also carries explicit text)."""
        if not has_selection:
            style = (
                "#selectedBar { background:#2b2b2b; border:1px solid #3d3d3d; "
                "border-left:3px solid #4a6172; border-radius:6px; }"
                "#selectedBar QLabel { background:transparent; font-weight:bold; "
                "color:#e9e9e9; }"
            )
        elif remaining > 0:
            style = (
                "#selectedBar { background:#2b2b2b; border:1px solid #3d3d3d; "
                "border-left:3px solid #e8a33d; border-radius:6px; }"
                "#selectedBar QLabel { background:transparent; font-weight:bold; "
                "color:#e9e9e9; }"
                "#selectedBar #selectedRemaining { color:#e8a33d; }"
            )
        else:
            style = (
                "#selectedBar { background:#2b2b2b; border:1px solid #3d3d3d; "
                "border-left:3px solid #4CAF50; border-radius:6px; }"
                "#selectedBar QLabel { background:transparent; font-weight:bold; "
                "color:#e9e9e9; }"
                "#selectedBar #selectedRemaining { color:#7fce95; }"
            )
        self.selected_bar.setStyleSheet(style)

    def _apply_account_data(self, account_data):
        """Store the sale-level account contract returned by
        ``get_client_sale_summaries()``: ``sales`` (one row per Sale with
        ``sale_id``/``date``/``state``/``is_historical``/``devis``/``total``/
        ``paid``/``remaining``) and ``payments`` (``payment_id``/``sale_id``/
        ``item_id``/``date``/``amount``).

        Monetary fields are normalized to Decimal (the LAN server ships them
        as numeric strings), and per-Sale totals are never recomputed here -
        the backend already caps ``paid`` at each sale total.
        """
        self.account_data = account_data or {"sales": [], "payments": []}
        self._account_loaded_once = True
        self.sales = []
        for sale in self.account_data.get("sales", []):
            self.sales.append({
                "sale_id": sale["sale_id"],
                "date": sale.get("date") or "",
                "state": sale.get("state") or "pending",
                "is_historical": bool(sale.get("is_historical")),
                "devis": sale.get("devis") or "",
                "total": to_decimal(sale.get("total") or 0),
                "paid": to_decimal(sale.get("paid") or 0),
                "remaining": to_decimal(sale.get("remaining") or 0),
            })
        self.payments = [dict(pay) for pay in self.account_data.get("payments", [])]
        self.devis_by_sale = {
            sale["sale_id"]: sale["devis"] for sale in self.sales
        }
        self._populate_purchases()
        self._populate_payments()

        total_bought = sum(
            (sale["total"] for sale in self.sales), Decimal("0")
        )
        # Sum payments specific to each sale
        total_paid_from_sales = sum((sale["paid"] for sale in self.sales), Decimal("0"))
        # Add general client payments (sale_id is None)
        general_paid = sum(
            (to_decimal(pay.get("amount") or 0) for pay in self.payments
             if pay.get("sale_id") is None),
            Decimal("0"),
        )
        total_paid = total_paid_from_sales + general_paid
        remaining = max(total_bought - total_paid, 0)

        self.total_bought_label.setText(f"{_format_money(total_bought)} {self.currency}")
        self.total_paid_label.setText(f"{_format_money(total_paid)} {self.currency}")
        self.total_paid_label.setStyleSheet("font-size:18px; font-weight:bold; color:#4CAF50;")
        self.remaining_label.setText(f"{_format_money(remaining)} {self.currency}")
        color = "#4CAF50" if remaining <= 0 else "#FF9800"
        self.remaining_label.setStyleSheet(f"font-size:18px; font-weight:bold; color:{color};")

        self.amount_input.clear()
        self.amount_input.setEnabled(False)
        self.add_payment_button.setEnabled(False)
        self.edit_payment_btn.setEnabled(False)
        self.print_statement_btn.setEnabled(True)
        self._update_print_selected_enabled()

    def refresh_data(self):
        """Kick off an async reload of this client's sale-level account data.

        get_client_sale_summaries() is a multi-row query - a synchronous RPC
        round-trip for a RemoteDatabase, and a real multi-join query even
        locally. Opening/refreshing this dialog must never block the GUI
        thread on it (that used to freeze the window under lock contention).
        """
        if self._account_thread is not None:
            return  # a refresh is already in flight

        thread = QThread()
        worker = _ClientAccountWorker(self.database, self.client_obj.id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # Safe thread cleanup lifecycle (mirrors BaseOperationDialog.LoadWorker)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_account_thread_finished)

        worker.finished.connect(self._on_account_loaded)
        worker.error.connect(self._on_account_load_error)

        self._account_thread = thread
        self._account_worker = worker
        _active_account_threads.add(thread)
        thread.finished.connect(lambda t=thread: _active_account_threads.discard(t))
        thread.start()

    def _on_account_thread_finished(self):
        self._account_thread = None
        self._account_worker = None

    @Slot(object)
    def _on_account_loaded(self, account_data):
        try:
            self._apply_account_data(account_data)
        except RuntimeError:
            pass  # dialog was closed/destroyed while the fetch was in flight
        except Exception:
            logger.exception(
                "View Client account data could not be applied: client_id=%s",
                self.client_obj.id,
            )
            try:
                QMessageBox.critical(
                    self,
                    "Client Account",
                    "The client account data could not be displayed. "
                    "See the log for details.",
                )
            except RuntimeError:
                pass

    @Slot(str)
    def _on_account_load_error(self, err_msg):
        mode = 'remote' if self.database.__class__.__name__ == 'RemoteDatabase' else 'local'
        try:
            logger.error(
                "View Client refresh failed: client_id=%s mode=%s error=%s",
                self.client_obj.id, mode, err_msg,
            )
            if not self._account_loaded_once:
                # First load failed - never pretend an empty account is the
                # truth. Keep the empty tables and tell the user.
                QMessageBox.critical(
                    self,
                    "Client Account",
                    f"Could not load this client's account from the host:\n{err_msg}",
                )
                return
            QMessageBox.warning(
                self,
                "Client Account",
                f"Could not refresh this client's account from the host:\n{err_msg}\n\n"
                "Showing the most recently loaded data.",
            )
            # Keep whatever self.account_data/self.purchases already held - a
            # failed refresh must not blank out data that was already shown.
            self._apply_account_data(self.account_data)
        except RuntimeError:
            pass

    def _populate_purchases(self):
        self.purchases_table.setRowCount(len(self.sales))
        for row, sale in enumerate(self.sales):
            devis = sale["devis"] or "-"
            values = [
                f"#{sale['sale_id']}",
                self._format_date(sale["date"]),
                f"Devis N° {devis}" if devis != "-" else "-",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, sale["sale_id"])
                item.setData(Qt.UserRole + 1, sale["sale_id"])

                if col in (0, 1):
                    item.setTextAlignment(Qt.AlignCenter)
                elif col == 2:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    item.setForeground(QColor("#8fc8d8"))

                self.purchases_table.setItem(row, col, item)

        count = len(self.sales)
        self.sales_count_label.setText(
            f"{count} record" if count == 1 else f"{count} records"
        )
        self.sales_stack.setCurrentIndex(0 if count else 1)

    def _populate_payments(self):
        rows = self.payments
        if not rows:
            self.payments_table.setRowCount(0)
            self.payments_count_label.setText("0 records")
            self.payments_stack.setCurrentIndex(1)
            self.edit_payment_btn.setEnabled(False)
            return

        self.payments_table.setRowCount(len(rows))
        for row_index, payment in enumerate(rows):
            sale_id = payment["sale_id"]
            if sale_id is not None:
                devis = self.devis_by_sale.get(sale_id) or "-"
                devis_display = f"Devis N° {devis}" if devis != "-" else "-"
                sale_display = f"#{sale_id}"
            else:
                devis_display = "General"
                sale_display = "-"
            values = [
                f"#{payment['payment_id']}",
                sale_display,
                self._format_date(payment["date"]),
                _format_money(payment["amount"]),
                devis_display,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, payment["payment_id"])
                item.setData(Qt.UserRole + 1, sale_id)

                if col in (0, 1, 2):
                    item.setTextAlignment(Qt.AlignCenter)
                elif col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setForeground(QColor("#7fce95"))
                elif col == 4:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                    item.setForeground(QColor("#8fc8d8"))
                self.payments_table.setItem(row_index, col, item)

        count = len(rows)
        self.payments_count_label.setText(
            f"{count} record" if count == 1 else f"{count} records"
        )
        self.payments_stack.setCurrentIndex(0)

    def _payment_selected(self, current_row, _current_col, _previous_row, _previous_col):
        if not getattr(self, "can_record_payment", False):
            self.edit_payment_btn.setEnabled(False)
            self.delete_payment_btn.setEnabled(False)
            return
        enabled = current_row >= 0 and current_row < len(self.payments)
        self.edit_payment_btn.setEnabled(enabled)
        self.delete_payment_btn.setEnabled(enabled)

    def _purchase_selected(self, current_row, _current_col, _previous_row, _previous_col):
        self._update_print_selected_enabled()
        if current_row < 0 or current_row >= len(self.sales):
            self.selected_sale_label.setText("Selected Sale #—")
            self.selected_devis_label.setText("Devis: —")
            self.selected_remaining_label.setText("Remaining: —")
            self._apply_selected_bar_style(Decimal("0"), has_selection=False)
            self.amount_input.clear()
            self.amount_input.setEnabled(True)
            self.amount_input.setPlaceholderText(
                f"Enter amount for general payment {self.currency}"
            )
            self.add_payment_button.setEnabled(True)
            return

        sale = self.sales[current_row]
        remaining = sale["remaining"]
        devis = sale["devis"] or "-"
        self.selected_sale_label.setText(f"Selected Sale #{sale['sale_id']}")
        self.selected_devis_label.setText(
            f"Devis: {devis}" if devis == "-" else f"Devis: Devis N° {devis}"
        )
        self.selected_remaining_label.setText(
            f"Remaining: {_format_money(remaining)} {self.currency}"
        )
        self._apply_selected_bar_style(remaining, has_selection=True)
        if remaining <= 0:
            self.amount_input.clear()
            self.amount_input.setPlaceholderText("This sale is fully paid")
            self.amount_input.setEnabled(False)
            self.add_payment_button.setEnabled(False)
            return

        self.amount_input.setEnabled(True)
        self.amount_input.clear()
        self.amount_input.setPlaceholderText(
            f"Enter up to {_format_money(remaining)} {self.currency}"
        )
        self.amount_input.setFocus()
        self.add_payment_button.setEnabled(True)

    def _update_print_selected_enabled(self):
        row = self.purchases_table.currentRow()
        has_selection = row >= 0 and row < len(self.sales)
        if hasattr(self, "print_selected_btn"):
            self.print_selected_btn.setEnabled(has_selection)

    def _company_profile_values(self):
        """Extract plain (GUI-thread) profile strings for the report worker."""
        profile = getattr(self.database, "remote_profile", None)
        if profile is None:
            manager = getattr(self.database, "profile_manager", None)
            profile = getattr(manager, "selected_profile", None) if manager else None
        if profile is None:
            return {}
        return {
            "company_name": profile.get_value("company name") or "",
            "company_address": profile.get_value("address") or "",
            "company_phone": profile.get_value("phone") or "",
            "company_email": profile.get_value("email") or "",
            "report_footer": profile.get_value("report footer") or "",
            "currency": profile.get_value("currency") or "MAD",
        }

    def _print_selected_sale(self):
        row = self.purchases_table.currentRow()
        if row < 0 or row >= len(self.sales):
            QMessageBox.information(
                self, "Select Sale", "Select a sale row to print first."
            )
            return
        sale_id = self.sales[row]["sale_id"]
        self.print_selected_btn.setEnabled(False)
        self.print_selected_btn.setText("Generating...")
        self._start_report_worker("selected_sale", sale_id)

    def _print_full_statement(self):
        self.print_statement_btn.setEnabled(False)
        self.print_statement_btn.setText("Generating...")
        self._start_report_worker("full_statement")

    def _start_report_worker(self, report_type, sale_id=None):
        if getattr(self, "_report_thread", None) is not None:
            return  # a report is already being generated

        client_data = {
            "id": self.client_obj.get_value("id"),
            "name": self.client_obj.get_value("name"),
            "username": self.client_obj.get_value("username"),
            "ice": self.client_obj.get_value("ice"),
            "phone": self.client_obj.get_value("phone"),
        }
        company_info = self._company_profile_values()
        worker = _ClientReportWorker(
            report_type,
            client_data,
            company_info,
            self.database,
            self.client_obj.id,
            sale_id,
        )
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        # Safe thread cleanup lifecycle (mirrors _ClientAccountWorker).
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(thread.quit)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_report_thread_finished)

        worker.finished.connect(self._on_report_finished)
        worker.failed.connect(self._on_report_failed)

        self._report_thread = thread
        self._report_worker = worker
        _active_report_threads.add(thread)
        thread.finished.connect(lambda t=thread: _active_report_threads.discard(t))
        thread.start()

    def _on_report_thread_finished(self):
        self._report_thread = None
        self._report_worker = None

    def _restore_print_buttons(self):
        if not hasattr(self, "print_selected_btn"):
            return
        self.print_selected_btn.setText("Print Selected Sale")
        self.print_statement_btn.setText("Print Full Client Statement")
        self.print_statement_btn.setEnabled(True)
        self._update_print_selected_enabled()

    @Slot(str)
    def _on_report_finished(self, pdf_path):
        try:
            self._restore_print_buttons()
            QMessageBox.information(
                self,
                "Report Ready",
                f"Report generated successfully.\n\nSaved to: {pdf_path}",
            )
            try:
                os.startfile(pdf_path)
            except Exception as error:
                logger.exception("Generated report could not be opened path=%s", pdf_path)
                QMessageBox.warning(
                    self,
                    "Warning",
                    f"Report generated but failed to open:\n{error}",
                )
        except RuntimeError:
            pass  # dialog was closed while the report was being generated

    @Slot(str)
    def _on_report_failed(self, error):
        try:
            self._restore_print_buttons()
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to generate the report:\n{error}",
            )
        except RuntimeError:
            pass

    def add_payment(self):
        if not self.can_record_payment:
            QMessageBox.information(
                self, "Read-Only Access", "You don't have permission to record payments."
            )
            return
        selected_row = self.purchases_table.currentRow()
        has_sale_selection = selected_row >= 0 and selected_row < len(self.sales)
        
        amount_text = self.amount_input.text()
        from core.calculations import parse_decimal_input, InputState
        state, amount_dec = parse_decimal_input(amount_text)
        if state in (InputState.INVALID, InputState.EMPTY, InputState.INTERMEDIATE):
            QMessageBox.warning(
                self,
                "Invalid Amount",
                "Enter the amount manually using numbers, for example 1500 or 1500.50.",
            )
            self.amount_input.setFocus()
            return

        amount = float(amount_dec)
        
        if has_sale_selection:
            sale = self.sales[selected_row]
            outstanding = sale["remaining"]
            if outstanding <= 0:
                QMessageBox.information(
                    self, "Sale Paid", "This sale is already fully paid."
                )
                return
            if amount_dec <= 0 or amount_dec > outstanding + Decimal("0.001"):
                QMessageBox.warning(
                    self,
                    "Invalid Amount",
                    f"Enter an amount between 0.01 and {_format_money(outstanding)} {self.currency}.",
                )
                return
            sale_id = sale["sale_id"]
            devis_text = f"sale #{sale_id} (Devis {sale['devis'] or '-'})"
        else:
            # General/client-level payment - no sale selected
            if amount_dec <= 0:
                QMessageBox.warning(
                    self,
                    "Invalid Amount",
                    f"Enter an amount greater than 0.",
                )
                return
            sale_id = None
            devis_text = "general client payment"

        date = self.date_input.date().toString("dd-MM-yyyy")
        try:
            self.database.add_client_payment(
                self.client_obj.id,
                sale_id,
                None,
                amount,
                date,
            )
        except Exception as error:
            QMessageBox.critical(self, "Payment Error", f"Could not save payment:\n{error}")
            return

        QMessageBox.information(
            self,
            "Payment Saved",
            f"Payment of {_format_money(amount)} {self.currency} was recorded for "
            f"{devis_text}.",
        )
        self.refresh_data()

    def _selected_payment(self):
        """Return the payment dict for the currently selected payment row."""
        row = self.payments_table.currentRow()
        if row < 0 or row >= len(self.payments):
            return None
        return self.payments[row]

    def _edit_selected_payment(self):
        if not self.can_record_payment:
            QMessageBox.information(
                self, "Read-Only Access", "You don't have permission to edit payments."
            )
            return
        if self._payment_edit_inflight:
            return  # an edit is already being saved
        payment = self._selected_payment()
        if not payment:
            QMessageBox.information(
                self, "Select Payment", "Select a payment row to edit first."
            )
            return

        sale = next(
            (s for s in self.sales if s["sale_id"] == payment["sale_id"]), None
        )
        if sale is None:
            QMessageBox.warning(
                self, "Edit Payment", "The sale of this payment could not be resolved."
            )
            return

        current = to_decimal(payment.get("amount") or 0)
        # No-overpayment rule (same as Add Payment): the edited amount must
        # keep the sale's total paid at or below its Total TTC.
        other_paid = sum(
            (
                to_decimal(p["amount"] or 0)
                for p in self.payments
                if p["payment_id"] != payment["payment_id"]
                and p["sale_id"] == payment["sale_id"]
            ),
            Decimal("0"),
        )
        max_allowed = sale["total"] - other_paid

        dialog = _EditPaymentDialog(
            self,
            payment_id=payment["payment_id"],
            sale_id=payment["sale_id"],
            devis=sale["devis"] or "-",
            current=current,
            max_allowed=max_allowed,
            currency=self.currency,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        new_amount = dialog.amount_decimal()
        self._start_payment_edit(payment["payment_id"], new_amount)

    def _start_payment_edit(self, payment_id, new_amount):
        self._payment_edit_inflight = True
        self.edit_payment_btn.setEnabled(False)
        self.edit_payment_btn.setText("Saving...")
        self.add_payment_button.setEnabled(False)

        thread = QThread()
        worker = _PaymentUpdateWorker(self.database, payment_id, float(new_amount))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_payment_edit_thread_finished)

        worker.finished.connect(self._on_payment_edit_finished)
        worker.error.connect(self._on_payment_edit_failed)

        self._payment_edit_thread = thread
        self._payment_edit_worker = worker
        thread.start()

    def _on_payment_edit_thread_finished(self):
        self._payment_edit_thread = None
        self._payment_edit_worker = None

    @Slot(object)
    def _on_payment_edit_finished(self, _payload):
        self._payment_edit_inflight = False
        self.edit_payment_btn.setText("Edit Payment Amount")
        try:
            QMessageBox.information(
                self, "Payment Updated", "The payment amount was updated."
            )
            self.refresh_data()
        except RuntimeError:
            pass

    @Slot(str)
    def _on_payment_edit_failed(self, error):
        self._payment_edit_inflight = False
        self.edit_payment_btn.setText("Edit Payment Amount")
        try:
            QMessageBox.critical(
                self, "Payment Error", f"Could not update the payment:\n{error}"
            )
            self.refresh_data()
        except RuntimeError:
            pass

    def _delete_selected_payment(self):
        if not self.can_record_payment:
            QMessageBox.information(
                self, "Read-Only Access", "You don't have permission to delete payments."
            )
            return
        if self._payment_delete_inflight:
            return  # a delete is already being saved
        if self._payment_edit_inflight:
            return  # an edit is already being saved
        payment = self._selected_payment()
        if not payment:
            QMessageBox.information(
                self, "Delete Payment", "Please select a payment to delete."
            )
            return

        sale = next(
            (s for s in self.sales if s["sale_id"] == payment["sale_id"]), None
        )
        if sale is None:
            QMessageBox.warning(
                self, "Delete Payment", "The sale of this payment could not be resolved."
            )
            return

        devis = sale.get("devis") or "-"
        if not self._confirm_payment_delete(payment, devis):
            return
        self._start_payment_delete(payment["payment_id"])

    def _confirm_payment_delete(self, payment, devis):
        """Modal confirmation before a payment is permanently deleted."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete Payment")
        box.setText(
            f"Are you sure you want to delete Payment #{payment['payment_id']}\n"
            f"Amount: {_format_money(payment['amount'])} {self.currency}\n"
            f"Sale: #{payment['sale_id']}\n"
            f"Devis: {devis}\n\n"
            "This action will remove this payment permanently."
        )
        delete_btn = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is delete_btn

    def _start_payment_delete(self, payment_id):
        self._payment_delete_inflight = True
        self.edit_payment_btn.setEnabled(False)
        self.delete_payment_btn.setEnabled(False)
        self.delete_payment_btn.setText("Deleting...")
        self.add_payment_button.setEnabled(False)

        thread = QThread()
        worker = _PaymentDeleteWorker(self.database, payment_id)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_payment_delete_thread_finished)

        worker.finished.connect(self._on_payment_delete_finished)
        worker.error.connect(self._on_payment_delete_failed)

        self._payment_delete_thread = thread
        self._payment_delete_worker = worker
        thread.start()

    def _on_payment_delete_thread_finished(self):
        self._payment_delete_thread = None
        self._payment_delete_worker = None

    @Slot(object)
    def _on_payment_delete_finished(self, _payload):
        self._payment_delete_inflight = False
        self.delete_payment_btn.setText("Delete Payment")
        try:
            QMessageBox.information(
                self, "Payment Deleted", "The payment was deleted."
            )
            self.refresh_data()
        except RuntimeError:
            pass

    @Slot(str)
    def _on_payment_delete_failed(self, error):
        self._payment_delete_inflight = False
        self.delete_payment_btn.setText("Delete Payment")
        try:
            QMessageBox.critical(
                self, "Delete Payment", f"Could not delete the payment:\n{error}"
            )
            self.refresh_data()
        except RuntimeError:
            pass


class _PaymentDeleteWorker(QObject):
    """Deletes one payment off the GUI thread."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, database, payment_id):
        super().__init__()
        self.database = database
        self.payment_id = payment_id

    @Slot()
    def run(self):
        try:
            if QThread.currentThread().isInterruptionRequested():
                return
            self.database.delete_client_payment(self.payment_id)
            self.finished.emit({"payment_id": self.payment_id})
        except Exception as e:
            logger.exception(
                "Payment delete failed: payment_id=%s", self.payment_id,
            )
            self.error.emit(str(e))
