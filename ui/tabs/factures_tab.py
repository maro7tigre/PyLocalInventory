"""Factures management UI backed by the dedicated invoice API."""

from decimal import Decimal
from uuid import uuid4

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from core.calculations import calculate_line_subtotal, calculate_operation_totals, round_money, to_decimal
from ui.facture_document import render_facture_preview_pages, render_facture_to_printer
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
        self.draft = None
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
        self.address = QLineEdit(); self.city = QLineEdit(); self.ice = QLineEdit()
        self.notes = QTextEdit(); self.notes.setMaximumHeight(70)
        form.addRow("Facture N°", self.number)
        form.addRow("Date", self.date)
        form.addRow("Client", self.client)
        form.addRow("Type", self.type)
        form.addRow("TVA %", self.tva)
        form.addRow("Adresse", self.address)
        form.addRow("Ville", self.city)
        form.addRow("ICE", self.ice)
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

    def load_draft(self, draft):
        """Populate a new editor from a selected Devis without issuing it yet."""
        self.draft = draft
        self.date.setDate(QDate.fromString(str(draft.get("date") or ""), "yyyy-MM-dd"))
        self.type.setCurrentIndex(max(0, self.type.findData(draft.get("facture_type") or "normal")))
        self.tva.setValue(float(draft.get("tva_rate") or 0)); self.notes.setPlainText(str(draft.get("notes") or ""))
        self.client.setCurrentIndex(self.client.findData(draft["client_id"]))
        self.items.setRowCount(0)
        for item in draft.get("items", []): self.add_line(item)
        self.update_totals()

    def _load_clients(self):
        catalog = self.database.get_sale_catalog(True, True, include_clients=True)
        self.line_catalog = {
            "product": {str(row["name"]): row for row in catalog.get("products", [])},
            "service": {str(row["name"]): row for row in catalog.get("services", [])},
        }
        self.client_records = {}
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
            self.client_records[int(client_id)] = client
        self.client.currentIndexChanged.connect(self._populate_client_snapshot)

    def _populate_client_snapshot(self):
        client = self.client_records.get(self.client.currentData())
        if client:
            self.address.setText(str(client.get("address") or ""))
            self.ice.setText(str(client.get("ice") or ""))

    def _load_facture(self, facture):
        self.date.setDate(QDate.fromString(str(facture["date"]), "yyyy-MM-dd"))
        self.type.setCurrentIndex(max(0, self.type.findData(facture["facture_type"])))
        self.tva.setValue(float(facture["tva_rate"])); self.address.setText(facture.get("client_address") or "")
        self.city.setText(facture.get("client_city") or ""); self.ice.setText(facture.get("client_ice") or "")
        self.notes.setPlainText(facture.get("notes") or "")
        index = self.client.findData(facture["client_id"])
        if index < 0:
            # Preserve historical invoices whose live client was removed; do
            # not silently replace their identity with the first client.
            client_id = int(facture["client_id"])
            self.client.addItem(f"{facture.get('client_name') or 'Client'} (historique)", client_id)
            self.client_records[client_id] = {"id": client_id}
            index = self.client.count() - 1
        self.client.setCurrentIndex(index)
        for item in facture["items"]:
            self.add_line(item)

    def add_line(self, item=None):
        row = self.items.rowCount(); self.items.insertRow(row)
        values = item or {}
        type_box = QComboBox()
        for label, value in (("Produit", "product"), ("Service", "service"), ("Texte libre", "manual"), ("Section", "section")):
            type_box.addItem(label, value)
        type_box.setCurrentIndex(max(0, type_box.findData(values.get("item_type") or "manual")))
        type_box.currentIndexChanged.connect(lambda _index, current=row: self._set_line_type(current))
        self.items.setCellWidget(row, 0, type_box)
        designation = QComboBox(); designation.setEditable(True)
        designation.setCurrentText(str(values.get("designation") or ""))
        designation.activated.connect(lambda _index, current=row: self._catalog_line_selected(current))
        self.items.setCellWidget(row, 1, designation)
        for col, key in enumerate(("information", "unit", "quantity", "unit_price", "discount_percentage"), 2):
            self.items.setItem(row, col, QTableWidgetItem(str(values.get(key, ""))))
        self._set_line_type(row)
        total = "" if values.get("item_type") == "section" else _money(calculate_line_subtotal(values.get("quantity", 0), values.get("unit_price", 0), values.get("discount_percentage", 0)))
        total_item = QTableWidgetItem(total); total_item.setFlags(total_item.flags() & ~Qt.ItemIsEditable)
        self.items.setItem(row, 7, total_item)

    def _set_line_type(self, row):
        type_box = self.items.cellWidget(row, 0)
        designation = self.items.cellWidget(row, 1)
        if not type_box or not designation:
            return
        current = str(type_box.currentData() or "manual")
        old = designation.currentText()
        designation.blockSignals(True); designation.clear()
        for name in self.line_catalog.get(current, {}):
            designation.addItem(name)
        designation.setCurrentText(old); designation.blockSignals(False)

    def _catalog_line_selected(self, row):
        type_box = self.items.cellWidget(row, 0); designation = self.items.cellWidget(row, 1)
        record = self.line_catalog.get(str(type_box.currentData()), {}).get(designation.currentText())
        if not record:
            return
        if not (self.items.item(row, 4).text().strip() if self.items.item(row, 4) else ""):
            self.items.item(row, 4).setText("1")
        if not (self.items.item(row, 5).text().strip() if self.items.item(row, 5) else ""):
            self.items.item(row, 5).setText(str(record.get("price") or 0))
        self.update_totals()

    def _line_data(self):
        lines = []
        for row in range(self.items.rowCount()):
            def value(col):
                widget = self.items.cellWidget(row, col)
                if widget and hasattr(widget, "currentText"):
                    return widget.currentText().strip()
                return self.items.item(row, col).text().strip() if self.items.item(row, col) else ""
            if not value(1):
                continue
            type_box = self.items.cellWidget(row, 0)
            item_type = str(type_box.currentData() if type_box else value(0)).casefold() or "manual"
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
                "client_address": self.address.text(), "client_city": self.city.text(), "client_ice": self.ice.text(),
                "notes": self.notes.toPlainText(),
                "operation_token": self.operation_token,
                **({key: self.draft[key] for key in ("source_sale_id", "source_devis") if key in self.draft} if self.draft else {}),
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


class DevisSelectorDialog(QDialog):
    """Search and select a Devis by its visible business data, never its PK."""
    def __init__(self, database, parent=None):
        super().__init__(parent); self.database = database; self.sale_id = None
        self.setWindowTitle("Sélectionner un Devis"); self.resize(900, 500)
        layout = QVBoxLayout(self); self.search = QLineEdit(); self.search.setPlaceholderText("N° Devis, client ou date")
        self.search.textChanged.connect(self.refresh); layout.addWidget(self.search)
        self.table = QTableWidget(0, 6); self.table.setHorizontalHeaderLabels(("Devis N°", "Client", "Date", "Total HT", "Total TTC", "Statut"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.table.cellDoubleClicked.connect(lambda *_: self.select())
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(self.select); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        rows = self.database.get_operation_summary_items(
            "Sales", search_text=self.search.text().strip() or None,
            search_columns=["devis", "client_name", "client_username", "date"], order_by="date", order_dir="desc"
        )
        self.table.setRowCount(len(rows))
        for row, sale in enumerate(rows):
            values = (sale.get("devis"), sale.get("client_name") or sale.get("client_username"), sale.get("date"),
                      _money(sale.get("total_ht") or 0), _money(sale.get("total_ttc") or 0), sale.get("state"))
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or "")); item.setData(Qt.UserRole, sale.get("ID") or sale.get("id")); self.table.setItem(row, col, item)

    def select(self):
        row = self.table.currentRow()
        if row < 0:
            return QMessageBox.information(self, "Devis", "Sélectionnez un devis.")
        self.sale_id = int(self.table.item(row, 0).data(Qt.UserRole)); self.accept()


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
        selector = DevisSelectorDialog(self.database, self)
        if not selector.exec(): return
        try:
            dialog = FactureEditor(self.database, parent=self)
            dialog.load_draft(self.database.get_facture_draft_from_sale(selector.sale_id))
            if dialog.exec(): self.refresh()
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
        profile = getattr(getattr(self.window(), "profile_manager", None), "selected_profile", None)
        payments = self.database.get_facture_payments(facture_id)
        dialog = QDialog(self); dialog.setWindowTitle("Aperçu facture"); dialog.resize(1050, 800); layout = QVBoxLayout(dialog)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); pages = QWidget(); page_layout = QVBoxLayout(pages)
        for image in render_facture_preview_pages(facture, payments, profile)[0]:
            page = QLabel(); page.setPixmap(QPixmap.fromImage(image)); page.setAlignment(Qt.AlignHCenter); page_layout.addWidget(page)
        scroll.setWidget(pages); layout.addWidget(scroll)
        actions = QHBoxLayout(); pdf = BlueButton("Enregistrer PDF"); pdf.clicked.connect(lambda: self._save_pdf(facture, payments, profile, dialog)); print_button = OrangeButton("Imprimer"); print_button.clicked.connect(lambda: self._print_facture(facture, payments, profile, dialog)); actions.addWidget(pdf); actions.addWidget(print_button); layout.addLayout(actions); dialog.exec()

    def _save_pdf(self, facture, payments, profile, parent):
        path, _ = QFileDialog.getSaveFileName(parent, "Enregistrer la facture", "", "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        render_facture_to_printer(printer, facture, payments, profile)

    def _print_facture(self, facture, payments, profile, parent):
        printer = QPrinter(QPrinter.HighResolution); dialog = QPrintDialog(printer, parent)
        if dialog.exec() == QDialog.Accepted:
            render_facture_to_printer(printer, facture, payments, profile)
