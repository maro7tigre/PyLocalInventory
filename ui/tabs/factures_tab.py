"""Factures management UI backed by the dedicated invoice API."""

from decimal import Decimal
from html import escape
from uuid import uuid4

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from core.calculations import calculate_line_subtotal, calculate_operation_totals, round_money, to_decimal
from core.moroccan_dirham_words import amount_to_words
from ui.widgets.themed_widgets import BlueButton, GreenButton, OrangeButton, RedButton


def _money(value):
    return f"{round_money(value):,.2f}".replace(",", " ")


class FactureEditor(QDialog):
    """Small editor for a persisted invoice snapshot, not a Sales editor clone."""

    columns = ("Type", "Désignation", "Information", "Unité", "Qté", "Prix HT", "Remise %", "Total HT")

    def __init__(self, database, facture=None, parent=None):
        super().__init__(parent)
        self.database = database
        self.facture = facture
        self.operation_token = uuid4().hex if facture is None else ""
        self.setWindowTitle("Modifier la facture" if facture else "Nouvelle facture")
        self.resize(1050, 680)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QLabel(facture["facture_number"] if facture else "Attribution à l'enregistrement")
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.client = QComboBox()
        self.client.setEditable(False)
        self.type = QComboBox()
        self.type.addItem("Facture normale", "normal")
        self.type.addItem("Facture d'acompte / avance", "advance")
        self.type.addItem("Facture de solde", "balance")
        self.tva = QDoubleSpinBox(); self.tva.setRange(0, 100); self.tva.setDecimals(3); self.tva.setValue(20)
        self.city = QLineEdit()
        self.notes = QTextEdit(); self.notes.setMaximumHeight(70)
        form.addRow("Facture N°", self.number)
        form.addRow("Date", self.date)
        form.addRow("Client", self.client)
        form.addRow("Type", self.type)
        form.addRow("TVA %", self.tva)
        form.addRow("Ville", self.city)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)
        self.items = QTableWidget(0, len(self.columns)); self.items.setHorizontalHeaderLabels(self.columns)
        self.items.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.items, 1)
        controls = QHBoxLayout()
        add = BlueButton("+ Ligne"); add.clicked.connect(self.add_line)
        remove = RedButton("Supprimer ligne"); remove.clicked.connect(lambda: self.items.removeRow(self.items.currentRow()))
        controls.addWidget(add); controls.addWidget(remove); controls.addStretch(1)
        self.total_ht = QLabel("Total HT: 0.00 MAD"); self.total_tva = QLabel("TVA: 0.00 MAD"); self.total_ttc = QLabel("Total TTC: 0.00 MAD")
        controls.addWidget(self.total_ht); controls.addWidget(self.total_tva); controls.addWidget(self.total_ttc)
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.items.itemChanged.connect(self.update_totals)
        self._load_clients()
        if facture:
            self._load_facture(facture)
        else:
            try:
                self.number.setText(f"Aperçu: {self.database.get_next_facture_preview()}")
            except Exception:
                pass
            self.add_line()

    def _load_clients(self):
        catalog = self.database.get_sale_catalog(False, False, include_clients=True)
        for client in catalog.get("clients", []):
            client_id = client.get("id")
            if client_id is None:
                raise RuntimeError("Client catalog is missing the canonical client ID")
            name = str(client.get("name") or "").strip()
            username = str(client.get("username") or "").strip()
            label = name or username or f"Client {client_id}"
            if username and username != label:
                label = f"{label} ({username})"
            self.client.addItem(label, int(client_id))

    def _load_facture(self, facture):
        self.date.setDate(QDate.fromString(str(facture["date"]), "yyyy-MM-dd"))
        self.type.setCurrentIndex(max(0, self.type.findData(facture["facture_type"])))
        self.tva.setValue(float(facture["tva_rate"])); self.city.setText(facture.get("client_city") or "")
        self.notes.setPlainText(facture.get("notes") or "")
        self.client.setCurrentIndex(max(0, self.client.findData(facture["client_id"])))
        for item in facture["items"]:
            self.add_line(item)

    def add_line(self, item=None):
        row = self.items.rowCount(); self.items.insertRow(row)
        values = item or {}
        for col, key in enumerate(("item_type", "designation", "information", "unit", "quantity", "unit_price", "discount_percentage")):
            self.items.setItem(row, col, QTableWidgetItem(str(values.get(key, ""))))
        total = "" if values.get("item_type") == "section" else _money(calculate_line_subtotal(values.get("quantity", 0), values.get("unit_price", 0), values.get("discount_percentage", 0)))
        total_item = QTableWidgetItem(total); total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        self.items.setItem(row, 7, total_item)

    def _line_data(self):
        lines = []
        for row in range(self.items.rowCount()):
            value = lambda col: (self.items.item(row, col).text().strip() if self.items.item(row, col) else "")
            if not value(1):
                continue
            item_type = value(0).casefold() or "manual"
            line = {"item_type": item_type, "designation": value(1), "information": value(2), "unit": value(3), "sort_order": row + 1}
            if item_type != "section":
                line.update({"quantity": value(4), "unit_price": value(5), "discount_percentage": value(6) or 0})
            lines.append(line)
        return lines

    def update_totals(self):
        try:
            gross = Decimal("0")
            for row, line in enumerate(self._line_data()):
                if line["item_type"] != "section":
                    total = calculate_line_subtotal(line["quantity"], line["unit_price"], line["discount_percentage"])
                    self.items.blockSignals(True); self.items.item(row, 7).setText(_money(total)); self.items.blockSignals(False)
                    gross += total
            totals = calculate_operation_totals(gross, 0, self.tva.value())
            self.total_ht.setText(f"Total HT: {_money(totals['total_ht'])} MAD")
            self.total_tva.setText(f"TVA: {_money(totals['vat_amount'])} MAD")
            self.total_ttc.setText(f"Total TTC: {_money(totals['total_ttc'])} MAD")
        except Exception:
            # Inputs can be temporarily incomplete while a cell is edited.
            return

    def save(self):
        if self.client.currentData() is None:
            QMessageBox.warning(self, "Facture", "Sélectionnez un client."); return
        try:
            result = self.database.save_facture_with_items({
                "client_id": self.client.currentData(), "date": self.date.date().toString("yyyy-MM-dd"),
                "facture_type": self.type.currentData(), "tva_rate": str(self.tva.value()),
                "client_city": self.city.text(), "notes": self.notes.toPlainText(),
                "operation_token": self.operation_token,
            }, self._line_data(), self.facture["id"] if self.facture else None)
            self.saved_id = result["facture_id"]; self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Facture", str(exc))


class FacturePaymentsDialog(QDialog):
    def __init__(self, database, facture_id, parent=None):
        super().__init__(parent); self.database = database; self.facture_id = facture_id
        self.setWindowTitle("Paiements de la facture"); self.resize(720, 420)
        layout = QVBoxLayout(self); self.summary = QLabel(); layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(("Date", "Montant", "Méthode", "Référence", "Notes")); layout.addWidget(self.table)
        form = QHBoxLayout(); self.date = QDateEdit(QDate.currentDate()); self.amount = QDoubleSpinBox(); self.amount.setRange(0.01, 999999999); self.amount.setDecimals(2)
        self.method = QComboBox(); self.method.addItems(("Espèces", "Chèque", "Virement", "Carte", "Autre")); self.reference = QLineEdit(); self.reference.setPlaceholderText("Référence")
        add = GreenButton("Ajouter paiement"); add.clicked.connect(self.add_payment)
        for widget in (self.date, self.amount, self.method, self.reference, add): form.addWidget(widget)
        layout.addLayout(form); self.refresh()

    def refresh(self):
        facture = self.database.get_facture(self.facture_id); self.summary.setText(f"TTC: {_money(facture['total_ttc'])} | Payé: {_money(facture['paid'])} | Reste: {_money(facture['remaining'])} | {facture['status']}")
        rows = self.database.get_facture_payments(self.facture_id); self.table.setRowCount(len(rows))
        for row, payment in enumerate(rows):
            for col, key in enumerate(("date", "amount", "method", "reference", "notes")):
                self.table.setItem(row, col, QTableWidgetItem(_money(payment[key]) if key == "amount" else str(payment[key] or "")))

    def add_payment(self):
        try:
            self.database.add_facture_payment(self.facture_id, str(self.amount.value()), self.date.date().toString("yyyy-MM-dd"), self.method.currentText(), self.reference.text())
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Paiement", str(exc))


class FacturesTab(QWidget):
    """Invoice list and actions; all data flows through Database/RPC APIs."""
    def __init__(self, database, parent=None):
        super().__init__(parent); self.database = database
        layout = QVBoxLayout(self); buttons = QHBoxLayout()
        actions = (("+ Nouvelle Facture", GreenButton, self.new_facture), ("Créer depuis Devis", BlueButton, self.from_devis), ("Modifier", OrangeButton, self.edit_facture), ("Paiements", BlueButton, self.payments), ("Aperçu / PDF / Imprimer", OrangeButton, self.preview), ("Supprimer", RedButton, self.delete_facture), ("Actualiser", BlueButton, self.refresh))
        self._action_buttons = {}
        for text, cls, slot in actions:
            button = cls(text); button.clicked.connect(slot); buttons.addWidget(button)
            self._action_buttons[text] = button
        buttons.addStretch(1); layout.addLayout(buttons)
        self.table = QTableWidget(0, 10); self.table.setHorizontalHeaderLabels(("ID", "Facture N°", "Client", "Date", "Total HT", "TVA", "Total TTC", "Payé", "Reste à payer", "Statut")); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.table)
        can_write = self.database.has_permission("Factures", "write")
        self._action_buttons["+ Nouvelle Facture"].setEnabled(can_write)
        self._action_buttons["Créer depuis Devis"].setEnabled(can_write)
        self._action_buttons["Modifier"].setEnabled(can_write)
        self._action_buttons["Paiements"].setEnabled(can_write)
        self._action_buttons["Supprimer"].setEnabled(
            self.database.has_permission("Factures", "delete")
        )
        self.refresh()

    def refresh(self):
        try:
            rows = self.database.list_factures(); self.table.setRowCount(len(rows))
            keys = ("id", "facture_number", "client_name", "date", "total_ht", "vat_amount", "total_ttc", "paid", "remaining", "status")
            for row, facture in enumerate(rows):
                for col, key in enumerate(keys): self.table.setItem(row, col, QTableWidgetItem(_money(facture[key]) if key in keys[4:9] else str(facture[key] or "")))
        except Exception as exc:
            QMessageBox.warning(self, "Factures", str(exc))

    # MainWindow uses these names for tab activation, backup restore, and its
    # staggered startup preload. Keeping the custom tab in that lifecycle
    # prevents an open Factures page from showing stale payment/status data.
    def refresh_table(self, force=False):
        self.refresh()

    def refresh_on_tab_switch(self):
        self.refresh()

    def selected_id(self):
        row = self.table.currentRow()
        return int(self.table.item(row, 0).text()) if row >= 0 and self.table.item(row, 0) else None

    def new_facture(self):
        dialog = FactureEditor(self.database, parent=self)
        if dialog.exec(): self.refresh()

    def from_devis(self):
        sale_id, accepted = QInputDialog.getInt(self, "Créer depuis Devis", "ID de la vente / devis:", 1, 1)
        if not accepted: return
        try:
            self.database.create_facture_from_sale(sale_id); self.refresh()
        except Exception as exc: QMessageBox.warning(self, "Facture", str(exc))

    def edit_facture(self):
        facture_id = self.selected_id()
        if not facture_id: return QMessageBox.information(self, "Facture", "Sélectionnez une facture.")
        dialog = FactureEditor(self.database, self.database.get_facture(facture_id), self)
        if dialog.exec(): self.refresh()

    def payments(self):
        facture_id = self.selected_id()
        if facture_id: FacturePaymentsDialog(self.database, facture_id, self).exec(); self.refresh()

    def delete_facture(self):
        facture_id = self.selected_id()
        if not facture_id:
            return
        if QMessageBox.question(self, "Supprimer", "Supprimer cette facture non payée ?") != QMessageBox.Yes:
            return
        try:
            self.database.delete_facture(facture_id)
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Facture", str(exc))

    def preview(self):
        facture_id = self.selected_id()
        if not facture_id: return
        facture = self.database.get_facture(facture_id)
        rows = []
        for item in facture["items"]:
            if item["item_type"] == "section":
                rows.append(f"<tr class='section'><td colspan='4'>{escape(str(item['designation']))}</td></tr>")
                continue
            rows.append("<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                escape(str(item["designation"])), escape(str(item.get("quantity") or "")),
                _money(item.get("unit_price") or 0), _money(calculate_line_subtotal(
                    item.get("quantity") or 0, item.get("unit_price") or 0,
                    item.get("discount_percentage") or 0,
                )),
            ))
        profile = getattr(getattr(self.window(), "profile_manager", None), "selected_profile", None)
        company = profile.get_value("company name") if profile else ""
        company_address = profile.get_value("address") if profile else ""
        source = f"Devis source: {facture.get('source_devis') or facture['source_sale_id']}" if facture.get("source_sale_id") else ""
        html = f"""<style>
            body {{ font-family: Arial, sans-serif; color: #222; margin: 22px; }}
            .header {{ border-bottom: 2px solid #183b63; padding-bottom: 12px; display: block; }}
            h1 {{ color: #183b63; text-align: right; margin: 0; }}
            table {{ border-collapse: collapse; margin-top: 24px; }} th {{ background: #183b63; color: white; }}
            th, td {{ border: 1px solid #555; padding: 7px; }} td:nth-child(n+2) {{ text-align: right; }}
            .section td {{ background: #eee; text-align: left !important; font-weight: bold; }}
            .totals {{ margin-left: auto; width: 48%; margin-top: 18px; }} .words {{ margin-top: 25px; font-style: italic; }}
            </style><div class='header'><b>{escape(str(company or ''))}</b><br>{escape(str(company_address or ''))}
            <h1>FACTURE</h1><div style='text-align:right'>N° {escape(facture['facture_number'])}<br>Date: {escape(str(facture['date']))}</div></div>
            <p><b>Client: {escape(facture['client_name'])}</b><br>{escape(facture.get('client_address') or '')}<br>{escape(facture.get('client_city') or '')}<br>ICE: {escape(facture.get('client_ice') or '')}<br>{escape(source)}</p>
            <table width='100%'><tr><th>Désignation</th><th>Qté</th><th>Prix HT</th><th>Total HT</th></tr>{''.join(rows)}</table>
            <table class='totals'><tr><td>Total HT</td><td>{_money(facture['total_ht'])} MAD</td></tr><tr><td>TVA</td><td>{_money(facture['vat_amount'])} MAD</td></tr><tr><td><b>Total TTC</b></td><td><b>{_money(facture['total_ttc'])} MAD</b></td></tr><tr><td>Payé</td><td>{_money(facture['paid'])} MAD</td></tr><tr><td>Reste à payer</td><td>{_money(facture['remaining'])} MAD</td></tr></table>
            <p class='words'>Arrêtée la présente Facture à la somme de : <b>{facture['amount_in_words']}</b></p>"""
        dialog = QDialog(self); dialog.setWindowTitle("Aperçu facture"); dialog.resize(850, 700); layout = QVBoxLayout(dialog); browser = QTextBrowser(); browser.setHtml(html); layout.addWidget(browser)
        actions = QHBoxLayout(); pdf = BlueButton("Enregistrer PDF"); pdf.clicked.connect(lambda: self._save_pdf(html, dialog)); print_button = OrangeButton("Imprimer"); print_button.clicked.connect(lambda: self._print_html(html, dialog)); actions.addWidget(pdf); actions.addWidget(print_button); layout.addLayout(actions); dialog.exec()

    def _save_pdf(self, html, parent):
        path, _ = QFileDialog.getSaveFileName(parent, "Enregistrer la facture", "", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        document = QTextDocument(); document.setHtml(html); document.print_(printer)

    def _print_html(self, html, parent):
        printer = QPrinter(QPrinter.HighResolution); dialog = QPrintDialog(printer, parent)
        if dialog.exec() == QDialog.Accepted:
            document = QTextDocument(); document.setHtml(html); document.print_(printer)
