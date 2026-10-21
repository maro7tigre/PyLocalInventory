"""Factures management UI backed by the dedicated invoice API."""

from decimal import Decimal
from uuid import uuid4

from PySide6.QtCore import QDate, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

from core.calculations import calculate_line_subtotal, calculate_operation_totals, round_money, to_decimal
from ui.facture_document import render_facture_preview_pages, render_facture_to_printer
from ui.widgets.themed_widgets import BlueButton, GreenButton, OrangeButton, RedButton

def _money(value):
    return f"{round_money(value):,.2f}".replace(",", " ")


_active_facture_request_jobs = {}


class _FactureRequestWorker(QObject):
    finished = Signal(object, object)
    failed = Signal(str, object)

    def __init__(self, database, requests, context):
        super().__init__()
        self.database = database
        self.requests = requests
        self.context = context

    @Slot()
    def run(self):
        worker_db = self.database
        close_worker_db = False
        try:
            from core.database import Database
            if isinstance(self.database, Database):
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, "language", "en")
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect(initialize_schema=False):
                    raise RuntimeError(
                        f"Worker could not connect to database: {worker_db.last_error}"
                    )
                close_worker_db = True

            results = []
            for method, args, kwargs in self.requests:
                if QThread.currentThread().isInterruptionRequested():
                    return
                results.append(getattr(worker_db, method)(*args, **kwargs))
            self.finished.emit(self.context, results)
        except Exception as exc:
            self.failed.emit(str(exc) or "Unknown error", self.context)
        finally:
            if close_worker_db:
                worker_db.close()


class _FactureAsyncRequests:
    def _init_facture_requests(self):
        self._facture_request_thread = None
        self._facture_request_worker = None
        self._facture_request_pending = None

    def _start_facture_request(self, database, requests, context=None):
        request = (database, requests, context)
        if self._facture_request_thread is not None:
            self._facture_request_pending = request
            return

        thread = QThread()
        worker = _FactureRequestWorker(database, requests, context)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_facture_request_loaded)
        worker.failed.connect(self._on_facture_request_failed)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        worker.failed.connect(thread.quit, Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_facture_request_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread_id = id(thread)
        _active_facture_request_jobs[thread_id] = (thread, worker)
        thread.destroyed.connect(
            lambda _obj=None, key=thread_id: _active_facture_request_jobs.pop(key, None)
        )
        self._facture_request_thread = thread
        self._facture_request_worker = worker
        thread.start()

    @Slot()
    def _on_facture_request_thread_finished(self):
        self._facture_request_thread = None
        self._facture_request_worker = None
        pending = self._facture_request_pending
        self._facture_request_pending = None
        if pending is not None:
            self._start_facture_request(*pending)


class _FacturesFetchWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, database):
        super().__init__()
        self.database = database

    @Slot()
    def run(self):
        worker_db = self.database
        close_worker_db = False
        try:
            # PostgreSQL cursors are thread-bound, so local list requests need
            # their own connection. RemoteDatabase performs one isolated RPC.
            from core.database import Database
            if isinstance(self.database, Database):
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, "language", "en")
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect(initialize_schema=False):
                    raise RuntimeError(
                        f"Worker could not connect to database: {worker_db.last_error}"
                    )
                close_worker_db = True
            if QThread.currentThread().isInterruptionRequested():
                return
            self.finished.emit(worker_db.list_factures())
        except Exception as exc:
            self.failed.emit(str(exc) or "Unknown error")
        finally:
            if close_worker_db:
                worker_db.close()


_active_facture_editor_jobs = {}


class _FactureEditorLoadWorker(QObject):
    loaded = Signal(object, object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, database, fetch_preview, facture_id=None, draft_request=None):
        super().__init__()
        self.database = database
        self.fetch_preview = fetch_preview
        self.facture_id = facture_id
        self.draft_request = draft_request

    @Slot()
    def run(self):
        worker_db = self.database
        close_worker_db = False
        try:
            from core.database import Database
            if isinstance(self.database, Database):
                worker_db = Database(self.database.profile_manager)
                worker_db.language = getattr(self.database, "language", "en")
                worker_db.registered_classes = self.database.registered_classes
                if not worker_db.connect(initialize_schema=False):
                    raise RuntimeError(
                        f"Worker could not connect to database: {worker_db.last_error}"
                    )
                close_worker_db = True

            if QThread.currentThread().isInterruptionRequested():
                return
            facture = (
                worker_db.get_facture(self.facture_id)
                if self.facture_id is not None else None
            )
            catalog = worker_db.get_sale_catalog(
                True, True, include_clients=True,
            )
            preview = None
            if self.fetch_preview and not QThread.currentThread().isInterruptionRequested():
                try:
                    preview = worker_db.get_next_facture_preview()
                except Exception:
                    pass
            draft = None
            if self.draft_request and not QThread.currentThread().isInterruptionRequested():
                sale_ids, facture_type, date = self.draft_request
                draft = worker_db.get_facture_draft_from_sales(
                    sale_ids, facture_type, date,
                )
            self.loaded.emit(catalog, {
                "preview": preview, "facture": facture, "draft": draft,
            })
        except Exception as exc:
            self.error.emit(str(exc) or "Unknown error")
        finally:
            if close_worker_db:
                try:
                    worker_db.close()
                except Exception:
                    pass
            self.finished.emit()


class FactureEditor(_FactureAsyncRequests, QDialog):
    """Small editor for a persisted invoice snapshot, not a Sales editor clone."""

    columns = ("Type", "Désignation", "Information", "Unité", "Qté", "Prix HT", "Remise %", "Total HT")

    def __init__(self, database, facture=None, parent=None, *, facture_id=None,
                 draft_request=None):
        super().__init__(parent)
        self.database = database
        self.facture = facture
        self._facture_id_to_load = facture_id
        self._draft_request_to_load = draft_request
        self.draft = None
        self.client_id = None
        self._init_facture_requests()
        self._saving = False
        self._draft_loading = False
        self._catalog_ready = False
        self._pending_draft = None
        self._catalog_thread = None
        self._catalog_worker = None
        self._active_facture = facture
        self.line_catalog = {"product": {}, "service": {}}
        self.client_records = {}
        self.operation_token = uuid4().hex if facture is None else ""
        self.setWindowTitle("Modifier la facture" if facture else "Nouvelle facture")
        self.resize(1050, 680)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QLabel(facture["facture_number"] if facture else "Attribution à l'enregistrement")
        self.catalog_status = QLabel("Chargement des clients et produits…")
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.client = QLineEdit(); self.client.setReadOnly(True)
        self.choose_client = BlueButton("Choisir client"); self.choose_client.clicked.connect(self.choose_client_dialog)
        client_row = QWidget(); client_layout = QHBoxLayout(client_row); client_layout.setContentsMargins(0, 0, 0, 0)
        client_layout.addWidget(self.client, 1); client_layout.addWidget(self.choose_client)
        self.type = QComboBox()
        self.type.addItem("Facture normale", "normal")
        self.type.addItem("Facture d'acompte / avance", "advance")
        self.type.addItem("Facture de solde", "balance")
        self.tva = QDoubleSpinBox(); self.tva.setRange(0, 100); self.tva.setDecimals(3); self.tva.setValue(20)
        self.address = QLineEdit(); self.city = QLineEdit(); self.ice = QLineEdit()
        self.notes = QTextEdit(); self.notes.setMaximumHeight(70)
        form.addRow("Facture N°", self.number)
        form.addRow("Date", self.date)
        form.addRow("Client", client_row)
        form.addRow("Type", self.type)
        form.addRow("TVA %", self.tva)
        form.addRow("Adresse", self.address)
        form.addRow("Ville", self.city)
        form.addRow("ICE", self.ice)
        form.addRow("Notes", self.notes)
        layout.addLayout(form)
        layout.addWidget(self.catalog_status)
        self.source_summary = QLabel("Aucun Devis sélectionné")
        self.type_details = QWidget(); self.type_layout = QFormLayout(self.type_details)
        self.select_devis = BlueButton("Sélectionner les devis"); self.select_devis.clicked.connect(self.choose_devis)
        self.type_layout.addRow(self.select_devis)
        self.type_layout.addRow("Devis sélectionnés", self.source_summary)
        self.selected_total = QLabel("0,00 MAD"); self.type_layout.addRow("Montant global des Devis", self.selected_total)
        self.advance_amount = QDoubleSpinBox(); self.advance_amount.setRange(0.01, 999999999); self.advance_amount.setDecimals(2)
        self.advance_designation = QLineEdit("AVANCE SUR TRAVAUX DE MENUISERIE EN BOIS")
        self.type_layout.addRow("Montant de l'avance TTC", self.advance_amount)
        self.type_layout.addRow("Désignation", self.advance_designation)
        self.previous_advance = QLabel("0,00 MAD"); self.remaining_balance = QLabel("0,00 MAD")
        self.type_layout.addRow("Déjà facturé", self.previous_advance)
        self.type_layout.addRow("Reste à facturer", self.remaining_balance)
        layout.addWidget(self.type_details)
        self.items = QTableWidget(0, len(self.columns)); self.items.setHorizontalHeaderLabels(self.columns)
        self.items.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.items, 1)
        controls = QHBoxLayout()
        self.add_line_button = BlueButton("+ Ligne"); self.add_line_button.clicked.connect(self.add_line)
        self.remove_line_button = RedButton("Supprimer ligne"); self.remove_line_button.clicked.connect(lambda: self.items.removeRow(self.items.currentRow()))
        controls.addWidget(self.add_line_button); controls.addWidget(self.remove_line_button); controls.addStretch(1)
        self.total_ht = QLabel("Total HT: 0.00 MAD"); self.total_tva = QLabel("TVA: 0.00 MAD"); self.total_ttc = QLabel("Total TTC: 0.00 MAD")
        controls.addWidget(self.total_ht); controls.addWidget(self.total_tva); controls.addWidget(self.total_ttc)
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.items.itemChanged.connect(lambda: (self.update_totals(), self._update_save_state()))
        self.type.currentIndexChanged.connect(self._update_type_ui)
        self.advance_amount.valueChanged.connect(self.update_totals)
        self._set_catalog_controls_enabled(False)
        self._update_type_ui()
        self._start_catalog_load()

    def load_draft(self, draft):
        """Populate a new editor from a selected Devis without issuing it yet."""
        if not self._catalog_ready:
            self._pending_draft = draft
            return
        self._apply_draft(draft)

    def _apply_draft(self, draft):
        self.draft = draft
        self.date.setDate(QDate.fromString(str(draft.get("date") or ""), "yyyy-MM-dd"))
        self.type.blockSignals(True)
        self.type.setCurrentIndex(max(0, self.type.findData(draft.get("facture_type") or "normal")))
        self.type.blockSignals(False)
        self.tva.setValue(float(draft.get("tva_rate") or 0)); self.notes.setPlainText(str(draft.get("notes") or ""))
        self.draft = draft
        self._set_client(draft["client_id"])
        self.source_summary.setText(draft.get("source_devis") or "Aucun Devis sélectionné")
        self.selected_total.setText(f"{_money(draft.get('selected_total_ttc') or 0)} MAD")
        self.previous_advance.setText(f"{_money(draft.get('previous_advance_ttc') or 0)} MAD")
        self.remaining_balance.setText(f"{_money(draft.get('remaining_ttc') or 0)} MAD")
        self.items.setRowCount(0)
        for item in draft.get("items", []): self.add_line(item)
        self._update_type_ui()

    def choose_devis(self):
        dialog = DevisSelectorDialog(self.database, self)
        if not dialog.exec():
            return
        self._draft_loading = True
        self._update_save_state()
        self.catalog_status.setText("Chargement du brouillon depuis les devis…")
        self.catalog_status.show()
        self._start_facture_request(self.database, [(
            "get_facture_draft_from_sales",
            (dialog.sale_ids, self.type.currentData(),
             self.date.date().toString("yyyy-MM-dd")),
            {},
        )], context=("choose_devis_draft", self.type.currentData()))

    def _refresh_special_draft(self, invoice_type):
        if self.facture:
            return
        draft = self.draft or {}
        source_ids = draft.get("source_sale_ids") or ([draft["source_sale_id"]] if draft.get("source_sale_id") else [])
        if not source_ids or (self.draft or {}).get("facture_type") == invoice_type:
            return
        self._draft_loading = True
        self._update_save_state()
        self.catalog_status.setText("Mise à jour des devis sélectionnés…")
        self.catalog_status.show()
        self._start_facture_request(self.database, [(
            "get_facture_draft_from_sales",
            (source_ids, invoice_type, self.date.date().toString("yyyy-MM-dd")),
            {},
        )], context=("special_draft", invoice_type))

    @Slot(object, object)
    def _on_facture_request_loaded(self, context, results):
        self._apply_facture_request(context, results)

    @Slot(str, object)
    def _on_facture_request_failed(self, error, context):
        self._show_facture_request_error(error, context)

    def _apply_facture_request(self, context, results):
        if context and context[0] in ("special_draft", "choose_devis_draft"):
            self._draft_loading = False
            self.catalog_status.hide()
            self._apply_draft(results[0])
            self._update_save_state()
            return
        if context == "save":
            self._saving = False
            self.setEnabled(True)
            self.saved_id = results[0]["facture_id"]
            self.accept()

    def _show_facture_request_error(self, error, context):
        if context == "save":
            self._saving = False
            self.setEnabled(True)
            QMessageBox.critical(self, "Facture", error)
            self._update_save_state()
        elif context and context[0] in ("special_draft", "choose_devis_draft"):
            self._draft_loading = False
            self.catalog_status.setText(f"Impossible de charger les devis : {error}")
            self.catalog_status.show()
            self._update_save_state()

    def _apply_catalog(self, catalog):
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
            self.client_records[int(client_id)] = client

    def _set_catalog_controls_enabled(self, enabled):
        for widget in (
            self.date, self.client, self.choose_client, self.type, self.tva,
            self.address, self.city, self.ice, self.notes, self.type_details,
            self.items, self.add_line_button, self.remove_line_button,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self.save_button.setEnabled(False)

    def _start_catalog_load(self):
        thread = QThread()
        worker = _FactureEditorLoadWorker(
            self.database,
            fetch_preview=self.facture is None and self._facture_id_to_load is None,
            facture_id=self._facture_id_to_load,
            draft_request=self._draft_request_to_load,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._on_catalog_loaded)
        worker.error.connect(self._on_catalog_load_error)
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_catalog_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread_id = id(thread)
        _active_facture_editor_jobs[thread_id] = (thread, worker)
        thread.destroyed.connect(
            lambda _obj=None, key=thread_id: _active_facture_editor_jobs.pop(key, None)
        )
        self._catalog_thread = thread
        self._catalog_worker = worker
        thread.start()

    @Slot(object, object)
    def _on_catalog_loaded(self, catalog, load_data):
        try:
            load_data = load_data or {}
            self._apply_catalog(catalog or {})
            self._catalog_ready = True
            self._set_catalog_controls_enabled(True)
            self.catalog_status.hide()
            loaded_facture = load_data.get("facture")
            if loaded_facture is not None:
                self.facture = loaded_facture
                self._active_facture = loaded_facture
                self.setWindowTitle("Modifier la facture")
            preview = load_data.get("preview")
            if preview is not None and self.facture is None:
                self.number.setText(f"Aperçu: {preview}")

            if self._active_facture is not None:
                self._load_facture(self._active_facture)
            elif load_data.get("draft") is not None:
                self._apply_draft(load_data["draft"])
            elif self._pending_draft is not None:
                draft = self._pending_draft
                self._pending_draft = None
                self._apply_draft(draft)
            else:
                self.add_line()
            self._update_save_state()
        except Exception as exc:
            self._on_catalog_load_error(str(exc) or "Unknown error")

    @Slot(str)
    def _on_catalog_load_error(self, error):
        self.catalog_status.setText("Impossible de charger les clients et produits.")
        self._set_catalog_controls_enabled(False)
        QMessageBox.warning(self, "Facture", f"Impossible de charger le catalogue :\n{error}")

    @Slot()
    def _on_catalog_thread_finished(self):
        self._catalog_thread = None
        self._catalog_worker = None

    def _set_client(self, client_id, populate_snapshot=True):
        self.client_id = int(client_id) if client_id is not None else None
        client = self.client_records.get(self.client_id)
        if client:
            name = str(client.get("name") or client.get("username") or f"Client {self.client_id}")
            self.client.setText(name)
            if not populate_snapshot:
                self._update_save_state()
                return
            self.address.setText(str(client.get("address") or ""))
            self.ice.setText(str(client.get("ice") or ""))
        self._update_save_state()

    def choose_client_dialog(self):
        dialog = ClientSelectorDialog(self.client_records, self)
        if dialog.exec():
            self._set_client(dialog.client_id)

    def _load_facture(self, facture):
        self.number.setText(str(facture.get("facture_number") or ""))
        self.operation_token = ""
        self.date.setDate(QDate.fromString(str(facture["date"]), "yyyy-MM-dd"))
        self.type.setCurrentIndex(max(0, self.type.findData(facture["facture_type"])))
        self.tva.setValue(float(facture["tva_rate"])); self.address.setText(facture.get("client_address") or "")
        self.city.setText(facture.get("client_city") or ""); self.ice.setText(facture.get("client_ice") or "")
        self.notes.setPlainText(facture.get("notes") or "")
        if facture["client_id"] not in self.client_records:
            # Preserve historical invoices whose live client was removed; do
            # not silently replace their identity with the first client.
            client_id = int(facture["client_id"])
            self.client_records[client_id] = {"id": client_id, "name": f"{facture.get('client_name') or 'Client'} (historique)"}
        self._set_client(facture["client_id"], populate_snapshot=False)
        self.source_summary.setText(facture.get("source_devis") or "Aucun Devis sélectionné")
        self.draft = {
            "source_sale_ids": [source["sale_id"] for source in facture.get("sources", []) if source.get("sale_id")],
            "source_devis": facture.get("source_devis") or "",
            "selected_total_ttc": facture.get("selected_total_ttc") or 0,
            "previous_advance_ttc": facture.get("previous_advance_ttc") or 0,
            "remaining_ttc": facture.get("total_ttc") or 0,
            "facture_type": facture["facture_type"],
            "remise": facture.get("remise") or 0,
            "remise_includes_line_discounts": facture.get("remise_includes_line_discounts", False),
        }
        if not self.draft["source_sale_ids"] and facture.get("source_sale_id"):
            self.draft["source_sale_ids"] = [facture["source_sale_id"]]
        for item in facture["items"]:
            self.add_line(item)
        if facture["facture_type"] == "advance":
            self.advance_amount.setValue(float(facture.get("total_ttc") or 0))
        self.type.setEnabled(False)
        self.select_devis.setEnabled(False)
        self.choose_client.setEnabled(False)

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
        designation.currentTextChanged.connect(lambda _text: self._update_save_state())
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
            if self.type.currentData() in ("advance", "balance"):
                total_ttc = (to_decimal(self.advance_amount.value()) if self.type.currentData() == "advance"
                             else to_decimal(self.draft.get("remaining_ttc") if self.draft else 0))
                total_ht = round_money(total_ttc / (Decimal("1") + to_decimal(self.tva.value()) / Decimal("100")))
                totals = calculate_operation_totals(total_ht, 0, self.tva.value())
                self.total_ht.setText(f"Total HT: {_money(totals['total_ht'])} MAD")
                self.total_tva.setText(f"TVA: {_money(totals['vat_amount'])} MAD")
                self.total_ttc.setText(f"Total TTC: {_money(totals['total_ttc'])} MAD")
                self._update_save_state()
                return
            gross = Decimal("0")
            raw_gross = Decimal("0")
            for row, line in enumerate(self._line_data()):
                if line["item_type"] != "section":
                    total = calculate_line_subtotal(line["quantity"], line["unit_price"], line["discount_percentage"])
                    self.items.blockSignals(True); self.items.item(row, 7).setText(_money(total)); self.items.blockSignals(False)
                    gross += total
                    raw_gross += to_decimal(line["quantity"]) * to_decimal(line["unit_price"])
            if self.draft and self.type.currentData() == "normal" and self.draft.get("remise_includes_line_discounts"):
                totals = calculate_operation_totals(raw_gross, self.draft.get("remise") or 0, self.tva.value())
            else:
                totals = calculate_operation_totals(gross, 0, self.tva.value())
            self.total_ht.setText(f"Total HT: {_money(totals['total_ht'])} MAD")
            self.total_tva.setText(f"TVA: {_money(totals['vat_amount'])} MAD")
            self.total_ttc.setText(f"Total TTC: {_money(totals['total_ttc'])} MAD")
            self._update_save_state()
        except Exception:
            # Inputs can be temporarily incomplete while a cell is edited.
            return

    def _update_type_ui(self):
        invoice_type = self.type.currentData()
        special = invoice_type in ("advance", "balance")
        if special:
            self._refresh_special_draft(invoice_type)
        has_sources = bool((self.draft or {}).get("source_sale_ids") or (self.draft or {}).get("source_sale_id"))
        self.type_details.setVisible(special or has_sources)
        self.items.setVisible(not special)
        for child in self.findChildren(QPushButton):
            if child.text() in ("+ Ligne", "Supprimer ligne"):
                child.setVisible(not special)
        self.type_layout.setRowVisible(self.advance_amount, invoice_type == "advance")
        self.type_layout.setRowVisible(self.advance_designation, invoice_type == "advance")
        self.type_layout.setRowVisible(self.previous_advance, special)
        self.type_layout.setRowVisible(self.remaining_balance, special)
        self.update_totals()

    def _update_save_state(self):
        if not hasattr(self, "save_button"):
            return
        if not self._catalog_ready or self._draft_loading or self._saving:
            self.save_button.setEnabled(False)
            return
        invoice_type = self.type.currentData()
        if invoice_type == "normal":
            enabled = self.client_id is not None and bool(self._line_data())
        else:
            draft = self.draft or {}
            source_ids = draft.get("source_sale_ids") or ([draft["source_sale_id"]] if draft.get("source_sale_id") else [])
            remaining = to_decimal(draft.get("remaining_ttc") or 0)
            if invoice_type == "advance":
                enabled = self.client_id is not None and bool(source_ids) and 0 < to_decimal(self.advance_amount.value()) <= remaining
            else:
                enabled = self.client_id is not None and bool(source_ids) and remaining > 0
        self.save_button.setEnabled(enabled)

    def save(self):
        if self.client_id is None:
            QMessageBox.warning(self, "Facture", "Sélectionnez un client."); return
        try:
            invoice_type = self.type.currentData()
            if invoice_type in ("advance", "balance") and not self.draft:
                raise ValueError("Une facture d'avance ou de solde doit être créée depuis un ou plusieurs Devis.")
            lines = self._line_data()
            if invoice_type in ("advance", "balance"):
                total_ttc = (to_decimal(self.advance_amount.value()) if invoice_type == "advance"
                             else to_decimal(self.draft.get("remaining_ttc") or 0))
                if total_ttc <= 0:
                    raise ValueError("Ces devis sont déjà entièrement facturés.")
                if invoice_type == "advance" and total_ttc > to_decimal(self.draft.get("remaining_ttc") or 0):
                    raise ValueError("Le montant de l'avance dépasse le reste à facturer.")
                total_ht = round_money(total_ttc / (Decimal("1") + to_decimal(self.tva.value()) / Decimal("100")))
                devis = self.draft.get("source_devis") or ""
                designation = (self.advance_designation.text().strip() or "AVANCE SUR TRAVAUX DE MENUISERIE EN BOIS"
                               if invoice_type == "advance" else "SOLDE SUR TRAVAUX DE MENUISERIE EN BOIS")
                lines = [{"item_type": "manual", "designation": f"{designation}\nSUIVANT DEVIS N° {devis}",
                          "unit": "ENS", "quantity": "1", "unit_price": str(total_ht), "discount_percentage": "0"}]
            data = {
                "client_id": self.client_id, "date": self.date.date().toString("yyyy-MM-dd"),
                "facture_type": self.type.currentData(), "tva_rate": str(self.tva.value()),
                "client_address": self.address.text(), "client_city": self.city.text(), "client_ice": self.ice.text(),
                "notes": self.notes.toPlainText(),
                "selected_total_ttc": self.draft.get("selected_total_ttc", 0) if self.draft else 0,
                "previous_advance_ttc": self.draft.get("previous_advance_ttc", 0) if self.draft else 0,
                "remise": self.draft.get("remise", 0) if self.draft and self.type.currentData() == "normal" else 0,
                "remise_includes_line_discounts": self.draft.get("remise_includes_line_discounts", False) if self.draft and self.type.currentData() == "normal" else False,
                "operation_token": self.operation_token,
                **({key: self.draft[key] for key in ("source_sale_ids", "source_sale_id", "source_devis") if key in self.draft} if self.draft else {}),
            }
            self._saving = True
            self.setEnabled(False)
            self._start_facture_request(self.database, [(
                "save_facture_with_items",
                (data, lines, self.facture["id"] if self.facture else None),
                {},
            )], context="save")
        except Exception as exc:
            self._saving = False
            self.setEnabled(True)
            QMessageBox.critical(self, "Facture", str(exc))

    def reject(self):
        if self._saving:
            return
        super().reject()

    def closeEvent(self, event):
        if self._saving:
            event.ignore()
            return
        thread = self._catalog_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.quit()
            thread.wait(2000)
        req_thread = getattr(self, "_facture_request_thread", None)
        if req_thread is not None and req_thread.isRunning():
            req_thread.requestInterruption()
            req_thread.quit()
            req_thread.wait(2000)
        super().closeEvent(event)


class FacturePaymentFormDialog(QDialog):
    """Shared form for editing a persisted Facture payment allocation."""
    def __init__(self, payment, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier paiement")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.date = QDateEdit(QDate.fromString(str(payment.get("date") or ""), "yyyy-MM-dd"))
        self.date.setCalendarPopup(True)
        self.amount = QDoubleSpinBox(); self.amount.setRange(0.01, 999999999); self.amount.setDecimals(2)
        self.amount.setValue(float(payment.get("amount") or 0))
        self.method = QComboBox(); self.method.addItems(("Espèces", "Chèque", "Virement", "Carte", "Autre"))
        self.method.setCurrentIndex(max(0, self.method.findText(str(payment.get("method") or "Autre"))))
        self.reference = QLineEdit(str(payment.get("reference") or ""))
        self.notes = QTextEdit(str(payment.get("notes") or "")); self.notes.setMaximumHeight(80)
        form.addRow("Date", self.date); form.addRow("Montant", self.amount)
        form.addRow("Méthode", self.method); form.addRow("Référence", self.reference); form.addRow("Notes", self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def values(self):
        return {
            "date": self.date.date().toString("yyyy-MM-dd"), "amount": str(self.amount.value()),
            "method": self.method.currentText(), "reference": self.reference.text(),
            "notes": self.notes.toPlainText(),
        }


class FacturePaymentsDialog(_FactureAsyncRequests, QDialog):
    def __init__(self, database, facture_id, parent=None):
        super().__init__(parent); self.database = database; self.facture_id = facture_id
        self._init_facture_requests()
        self._loaded = False
        self._busy = False
        self.setWindowTitle("Paiements de la facture"); self.resize(820, 480)
        layout = QVBoxLayout(self); self.load_status = QLabel("Chargement des paiements…"); layout.addWidget(self.load_status)
        self.retry_button = BlueButton("Réessayer"); self.retry_button.clicked.connect(self.refresh); self.retry_button.hide(); layout.addWidget(self.retry_button)
        self.summary = QLabel(); layout.addWidget(self.summary)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(("Date", "Montant", "Méthode", "Référence", "Notes"))
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self._update_actions)
        layout.addWidget(self.table)
        form = QHBoxLayout(); self.date = QDateEdit(QDate.currentDate()); self.amount = QDoubleSpinBox(); self.amount.setRange(0.01, 999999999); self.amount.setDecimals(2)
        self.method = QComboBox(); self.method.addItems(("Espèces", "Chèque", "Virement", "Carte", "Autre")); self.reference = QLineEdit(); self.reference.setPlaceholderText("Référence")
        self.notes = QLineEdit(); self.notes.setPlaceholderText("Notes")
        self.add_button = GreenButton("Ajouter paiement"); self.add_button.clicked.connect(self.add_payment)
        for widget in (self.date, self.amount, self.method, self.reference, self.notes, self.add_button): form.addWidget(widget)
        layout.addLayout(form)
        actions = QHBoxLayout(); self.edit_button = BlueButton("Modifier paiement"); self.edit_button.clicked.connect(self.edit_payment)
        self.delete_button = RedButton("Supprimer paiement"); self.delete_button.clicked.connect(self.delete_payment)
        actions.addStretch(1); actions.addWidget(self.edit_button); actions.addWidget(self.delete_button); layout.addLayout(actions)
        self.payments = []; self.refresh()

    def refresh(self):
        self.load_status.setText("Chargement des paiements…")
        self.load_status.show(); self.retry_button.hide()
        self._set_busy(True)
        self._start_facture_request(self.database, [
            ("get_facture", (self.facture_id,), {}),
            ("get_facture_payments", (self.facture_id,), {}),
        ], context="load")

    def _set_busy(self, busy):
        self._busy = busy
        enabled = self._loaded and not busy
        for widget in (self.table, self.date, self.amount, self.method,
                       self.reference, self.notes, self.add_button):
            widget.setEnabled(enabled)
        self._update_actions()

    @Slot(object, object)
    def _on_facture_request_loaded(self, context, results):
        self._apply_facture_request(context, results)

    @Slot(str, object)
    def _on_facture_request_failed(self, error, context):
        self._show_facture_request_error(error, context)

    def _apply_facture_request(self, context, results):
        if context != "load":
            if context == "add":
                self.reference.clear(); self.notes.clear()
            self.refresh()
            return

        facture, self.payments = results
        self.summary.setText(
            f"TTC: {_money(facture['total_ttc'])} | Payé: {_money(facture['paid'])} | "
            f"Reste: {_money(facture['remaining'])} | {facture['status']}"
        )
        self.table.setRowCount(len(self.payments))
        for row, payment in enumerate(self.payments):
            for col, key in enumerate(("date", "amount", "method", "reference", "notes")):
                item = QTableWidgetItem(_money(payment[key]) if key == "amount" else str(payment[key] or ""))
                item.setData(Qt.UserRole, int(payment["id"])); self.table.setItem(row, col, item)
        self._loaded = True
        self.load_status.hide()
        self._set_busy(False)
        self._update_actions()

    def _show_facture_request_error(self, error, context):
        self._set_busy(False)
        self.load_status.setText("Impossible de charger les paiements.")
        self.load_status.show(); self.retry_button.show()
        QMessageBox.warning(self, "Paiement", error)

    def _selected_payment(self):
        row = self.table.currentRow()
        return self.payments[row] if 0 <= row < len(self.payments) else None

    def _update_actions(self):
        selected = self._loaded and not self._busy and self._selected_payment() is not None
        self.edit_button.setEnabled(selected); self.delete_button.setEnabled(selected)

    def add_payment(self):
        if not self._loaded or self._busy:
            return
        self._set_busy(True)
        self._start_facture_request(self.database, [(
            "add_facture_payment",
            (self.facture_id, str(self.amount.value()), self.date.date().toString("yyyy-MM-dd"),
             self.method.currentText(), self.reference.text(), self.notes.text()),
            {},
        )], context="add")

    def edit_payment(self):
        payment = self._selected_payment()
        if not payment:
            return
        dialog = FacturePaymentFormDialog(payment, self)
        if not dialog.exec():
            return
        values = dialog.values()
        self._set_busy(True)
        self._start_facture_request(self.database, [(
            "update_facture_payment",
            (self.facture_id, payment["id"], values["amount"], values["date"],
             values["method"], values["reference"], values["notes"]),
            {},
        )], context="update")

    def delete_payment(self):
        payment = self._selected_payment()
        if not payment:
            return
        if QMessageBox.question(self, "Supprimer paiement", "Supprimer ce paiement ?") != QMessageBox.Yes:
            return
        self._set_busy(True)
        self._start_facture_request(self.database, [(
            "delete_facture_payment", (self.facture_id, payment["id"]), {},
        )], context="delete")

    def reject(self):
        if self._busy:
            return
        super().reject()

    def closeEvent(self, event):
        if self._busy:
            event.ignore()
            return
        req_thread = getattr(self, "_facture_request_thread", None)
        if req_thread is not None and req_thread.isRunning():
            req_thread.requestInterruption()
            req_thread.quit()
            req_thread.wait(2000)
        super().closeEvent(event)


class ClientSelectorDialog(QDialog):
    """Searchable client picker, kept outside the invoice editor."""
    def __init__(self, clients, parent=None):
        super().__init__(parent); self.clients = clients; self.client_id = None
        self.setWindowTitle("Choisir un client"); self.resize(620, 420)
        layout = QVBoxLayout(self); self.search = QLineEdit(); self.search.setPlaceholderText("Nom, société ou identifiant client")
        self.search.textChanged.connect(self.refresh); layout.addWidget(self.search)
        self.table = QTableWidget(0, 3); self.table.setHorizontalHeaderLabels(("Client", "Adresse", "ICE"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.table.cellDoubleClicked.connect(lambda *_: self.select())
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(self.select); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        needle = self.search.text().casefold().strip()
        rows = [client for client in self.clients.values() if needle in " ".join(str(client.get(key) or "") for key in ("name", "username", "address", "ice")).casefold()]
        self.table.setRowCount(len(rows))
        for row, client in enumerate(rows):
            values = (client.get("name") or client.get("username") or f"Client {client['id']}", client.get("address") or "", client.get("ice") or "")
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setData(Qt.UserRole, int(client["id"])); self.table.setItem(row, col, item)

    def select(self):
        row = self.table.currentRow()
        if row < 0:
            return QMessageBox.information(self, "Client", "Sélectionnez un client.")
        self.client_id = int(self.table.item(row, 0).data(Qt.UserRole)); self.accept()


class DevisSelectorDialog(_FactureAsyncRequests, QDialog):
    """Professional visible-data multi-selection; no database IDs are exposed."""
    def __init__(self, database, parent=None):
        super().__init__(parent); self.database = database; self.sale_ids = []
        self._init_facture_requests()
        self._query_generation = 0
        self.setWindowTitle("Sélectionner des Devis"); self.resize(950, 500)
        layout = QVBoxLayout(self); self.search = QLineEdit(); self.search.setPlaceholderText("N° Devis, client ou date")
        self._search_timer = QTimer(self); self._search_timer.setSingleShot(True); self._search_timer.setInterval(150); self._search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(self._schedule_refresh); layout.addWidget(self.search)
        self.load_status = QLabel("Chargement des devis…"); layout.addWidget(self.load_status)
        self.table = QTableWidget(0, 7); self.table.setHorizontalHeaderLabels(("", "Devis N°", "Client", "Date", "Total HT", "Total TTC", "Statut"))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)
        actions = QHBoxLayout(); all_button = BlueButton("Tout sélectionner"); all_button.clicked.connect(self.select_all); actions.addWidget(all_button); actions.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(self.select); buttons.rejected.connect(self.reject); actions.addWidget(buttons); layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        self._query_generation += 1
        generation = self._query_generation
        self.load_status.setText("Recherche des devis…")
        self.load_status.show()
        self._start_facture_request(self.database, [(
            "get_operation_summary_items", ("Sales",), {
                "search_text": self.search.text().strip() or None,
                "search_columns": ["devis", "client_name", "client_username", "date"],
                "order_by": "date", "order_dir": "desc",
            },
        )], context=generation)

    def _schedule_refresh(self):
        self._query_generation += 1
        self._search_timer.start()

    @Slot(object, object)
    def _on_facture_request_loaded(self, context, results):
        self._apply_facture_request(context, results)

    @Slot(str, object)
    def _on_facture_request_failed(self, error, context):
        self._show_facture_request_error(error, context)

    def _apply_facture_request(self, context, results):
        if context != self._query_generation:
            return
        rows = results[0]
        self.table.setRowCount(len(rows))
        for row, sale in enumerate(rows):
            values = (sale.get("devis"), sale.get("client_name") or sale.get("client_username"), sale.get("date"),
                      _money(sale.get("total_ht") or 0), _money(sale.get("total_ttc") or 0), sale.get("state"))
            check = QTableWidgetItem(); check.setFlags(check.flags() | Qt.ItemIsUserCheckable); check.setCheckState(Qt.Unchecked); check.setData(Qt.UserRole, sale.get("ID") or sale.get("id")); self.table.setItem(row, 0, check)
            for col, value in enumerate(values, 1):
                item = QTableWidgetItem(str(value or "")); item.setData(Qt.UserRole, sale.get("ID") or sale.get("id")); self.table.setItem(row, col, item)
        self.load_status.setText(f"{len(rows)} devis trouvé(s)")
        self.load_status.setVisible(not bool(rows))

    def _show_facture_request_error(self, error, context):
        if context == self._query_generation:
            self.load_status.setText(f"Impossible de charger les devis : {error}")
            self.load_status.show()

    def select_all(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.Checked)

    def select(self):
        self.sale_ids = [int(self.table.item(row, 0).data(Qt.UserRole)) for row in range(self.table.rowCount()) if self.table.item(row, 0).checkState() == Qt.Checked]
        if not self.sale_ids:
            return QMessageBox.information(self, "Devis", "Sélectionnez au moins un devis.")
        self.accept()

    def closeEvent(self, event):
        req_thread = getattr(self, "_facture_request_thread", None)
        if req_thread is not None and req_thread.isRunning():
            req_thread.requestInterruption()
            req_thread.quit()
            req_thread.wait(2000)
        super().closeEvent(event)


class FacturePreviewDialog(QDialog):
    """Fit-page viewer for the same QPainter pages used for PDF and printing."""
    def __init__(self, images, parent=None):
        super().__init__(parent); self.images = images; self.page_index = 0; self.zoom = 0
        self.setWindowTitle("Aperçu facture"); self.resize(1050, 800)
        layout = QVBoxLayout(self)
        self.preview = QScrollArea(); self.preview.setWidgetResizable(False)
        self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.page = QLabel(); self.page.setAlignment(Qt.AlignCenter); self.page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview.setWidget(self.page); layout.addWidget(self.preview, 1)
        controls = QHBoxLayout(); fit = BlueButton("Ajuster à la page"); fit.clicked.connect(self.fit_page)
        full = BlueButton("100 %"); full.clicked.connect(lambda: self.set_zoom(1.0))
        minus = BlueButton("Zoom -"); minus.clicked.connect(lambda: self.set_zoom((self.zoom or self._fit_scale()) / 1.2))
        plus = BlueButton("Zoom +"); plus.clicked.connect(lambda: self.set_zoom((self.zoom or self._fit_scale()) * 1.2))
        self.page_number = QSpinBox(); self.page_number.setRange(1, max(1, len(images))); self.page_number.valueChanged.connect(self.change_page)
        for widget in (fit, full, minus, plus, QLabel("Page"), self.page_number): controls.addWidget(widget)
        controls.addStretch(1); layout.addLayout(controls); self.fit_page()

    def _fit_scale(self):
        image = self.images[self.page_index]
        viewport = self.preview.viewport().size()
        return min(max(0.05, viewport.width() / image.width()), max(0.05, viewport.height() / image.height()))

    def update_page(self):
        image = self.images[self.page_index]; scale = self.zoom or self._fit_scale()
        pixmap = QPixmap.fromImage(image).scaled(max(1, int(image.width() * scale)), max(1, int(image.height() * scale)), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        viewport = self.preview.viewport().size()
        self.page.setPixmap(pixmap)
        self.page.resize(max(viewport.width(), pixmap.width()), max(viewport.height(), pixmap.height()))

    def fit_page(self):
        self.zoom = 0; self.update_page()

    def set_zoom(self, zoom):
        self.zoom = max(0.05, zoom); self.update_page()

    def change_page(self, number):
        self.page_index = number - 1; self.update_page()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.zoom:
            self.update_page()


class FactureTypeDialog(QDialog):
    """Choose the billing workflow before opening an invoice editor."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.facture_type = None
        self.setWindowTitle("Type de facture")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choisissez le type de facture :"))
        choices = (
            ("FACTURE NORMALE", "Facturer normalement des produits/services", "normal"),
            ("FACTURE D'ACOMPTE", "Facturer une avance sur un ou plusieurs Devis", "advance"),
            ("FACTURE DE SOLDE", "Facturer uniquement le montant restant à facturer", "balance"),
        )
        for title, detail, value in choices:
            button = BlueButton(f"{title}\n{detail}")
            button.clicked.connect(lambda _checked=False, selected=value: self._select(selected))
            layout.addWidget(button)
        cancel = QDialogButtonBox(QDialogButtonBox.Cancel)
        cancel.rejected.connect(self.reject)
        layout.addWidget(cancel)

    def _select(self, facture_type):
        self.facture_type = facture_type
        self.accept()


class FacturesTab(_FactureAsyncRequests, QWidget):
    """Invoice list and actions; all data flows through Database/RPC APIs."""
    def __init__(self, database, parent=None):
        super().__init__(parent); self.database = database
        self._init_facture_requests()
        self._refresh_thread = None
        self._refresh_worker = None
        self._refresh_pending = False
        layout = QVBoxLayout(self); buttons = QHBoxLayout()
        actions = (("+ Nouvelle Facture", GreenButton, self.new_facture), ("Créer depuis Devis", BlueButton, self.from_devis), ("Modifier", OrangeButton, self.edit_facture), ("Paiements", BlueButton, self.payments), ("Aperçu / PDF / Imprimer", OrangeButton, self.preview), ("Supprimer", RedButton, self.delete_facture), ("Actualiser", BlueButton, self.refresh))
        self._action_buttons = {}
        for text, cls, slot in actions:
            button = cls(text); button.clicked.connect(slot); buttons.addWidget(button)
            self._action_buttons[text] = button
        buttons.addStretch(1); layout.addLayout(buttons)
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(("ID", "Facture N°", "Type", "Client", "Date", "Devis source", "Total TTC", "Statut")); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.table)
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
        if self._refresh_thread is not None:
            self._refresh_pending = True
            return
        thread = QThread(self)
        worker = _FacturesFetchWorker(self.database)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._render_factures)
        worker.failed.connect(self._show_refresh_error)
        # Quit from the worker thread so closeEvent() can safely wait without
        # depending on the GUI event loop to deliver a queued signal.
        worker.finished.connect(thread.quit, Qt.DirectConnection)
        worker.failed.connect(thread.quit, Qt.DirectConnection)
        thread.finished.connect(self._on_refresh_finished)
        self._refresh_thread = thread
        self._refresh_worker = worker
        self._action_buttons["Actualiser"].setEnabled(False)
        thread.start()

    @Slot(object)
    def _render_factures(self, rows):
        self.table.setRowCount(len(rows))
        keys = ("id", "facture_number", "facture_type", "client_name", "date", "source_devis", "total_ttc", "status")
        for row, facture in enumerate(rows):
            for col, key in enumerate(keys):
                value = facture.get(key)
                if key == "facture_type":
                    value = {"normal": "Normale", "advance": "Avance", "balance": "Solde"}.get(value, value)
                self.table.setItem(row, col, QTableWidgetItem(_money(value) if key == "total_ttc" else str(value or "")))

    @Slot(str)
    def _show_refresh_error(self, error):
        QMessageBox.warning(self, "Factures", error)

    @Slot()
    def _on_refresh_finished(self):
        thread = self._refresh_thread
        self._refresh_thread = None
        self._refresh_worker = None
        self._action_buttons["Actualiser"].setEnabled(True)
        if thread is not None:
            thread.deleteLater()
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def closeEvent(self, event):
        thread = self._refresh_thread
        if thread is not None and thread.isRunning():
            thread.requestInterruption()
            thread.quit()
            thread.wait(5000)
        req_thread = getattr(self, "_facture_request_thread", None)
        if req_thread is not None and req_thread.isRunning():
            req_thread.requestInterruption()
            req_thread.quit()
            req_thread.wait(2000)
        super().closeEvent(event)

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
        chooser = FactureTypeDialog(self)
        if not chooser.exec():
            return
        dialog = FactureEditor(self.database, parent=self)
        dialog.type.setCurrentIndex(dialog.type.findData(chooser.facture_type))
        if dialog.exec(): self.refresh()

    def from_devis(self):
        selector = DevisSelectorDialog(self.database, self)
        if not selector.exec(): return
        chooser = FactureTypeDialog(self)
        if not chooser.exec():
            return
        dialog = FactureEditor(
            self.database, parent=self,
            draft_request=(selector.sale_ids, chooser.facture_type,
                           QDate.currentDate().toString("yyyy-MM-dd")),
        )
        if dialog.exec(): self.refresh()

    def edit_facture(self):
        facture_id = self.selected_id()
        if not facture_id: return QMessageBox.information(self, "Facture", "Sélectionnez une facture.")
        dialog = FactureEditor(self.database, parent=self, facture_id=facture_id)
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
        self._action_buttons["Supprimer"].setEnabled(False)
        self._start_facture_request(self.database, [
            ("delete_facture", (facture_id,), {}),
        ], context=("delete", facture_id))

    def preview(self):
        facture_id = self.selected_id()
        if not facture_id: return
        self._action_buttons["Aperçu / PDF / Imprimer"].setEnabled(False)
        profile = self._get_report_profile()
        self._start_facture_request(self.database, [
            ("get_facture", (facture_id,), {}),
            ("get_facture_payments", (facture_id,), {}),
        ], context=("preview", facture_id, profile))

    @Slot(object, object)
    def _on_facture_request_loaded(self, context, results):
        self._apply_facture_request(context, results)

    @Slot(str, object)
    def _on_facture_request_failed(self, error, context):
        self._show_facture_request_error(error, context)

    def _apply_facture_request(self, context, results):
        if isinstance(context, tuple) and context[0] == "preview":
            self._action_buttons["Aperçu / PDF / Imprimer"].setEnabled(True)
            _tag, _facture_id, profile = context
            facture, payments = results
            dialog = FacturePreviewDialog(render_facture_preview_pages(facture, payments, profile)[0], self)
            layout = dialog.layout()
            actions = QHBoxLayout()
            pdf = BlueButton("Enregistrer PDF")
            pdf.clicked.connect(lambda: self._save_pdf(facture, payments, profile, dialog))
            print_button = OrangeButton("Imprimer")
            print_button.clicked.connect(lambda: self._print_facture(facture, payments, profile, dialog))
            close = RedButton("Fermer")
            close.clicked.connect(dialog.reject)
            actions.addWidget(pdf)
            actions.addWidget(print_button)
            actions.addStretch(1)
            actions.addWidget(close)
            layout.addLayout(actions)
            dialog.exec()
        elif isinstance(context, tuple) and context[0] == "delete":
            self._action_buttons["Supprimer"].setEnabled(
                self.database.has_permission("Factures", "delete")
            )
            self.refresh()

    def _show_facture_request_error(self, error, context):
        if isinstance(context, tuple) and context[0] == "preview":
            self._action_buttons["Aperçu / PDF / Imprimer"].setEnabled(True)
            QMessageBox.warning(self, "Aperçu facture", error)
        elif isinstance(context, tuple) and context[0] == "delete":
            self._action_buttons["Supprimer"].setEnabled(
                self.database.has_permission("Factures", "delete")
            )
            QMessageBox.warning(self, "Facture", error)

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

    def _get_report_profile(self):
        """Match the profile source order used by the existing report dialogs."""
        profile_manager = getattr(self.database, "profile_manager", None)
        return (
            getattr(profile_manager, "selected_profile", None)
            or getattr(getattr(self.window(), "profile_manager", None), "selected_profile", None)
            or getattr(self.database, "remote_profile", None)
        )
