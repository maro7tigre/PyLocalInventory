"""Reusable client/sale attachment section with no host path exposure."""
import base64
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QBuffer, QIODevice, QSize
from PySide6.QtGui import QGuiApplication, QImage, QPixmap, QDesktopServices, QIcon
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QMessageBox, QLineEdit, QComboBox,
    QInputDialog, QDialog, QLabel, QScrollArea, QCheckBox, QDialogButtonBox, QHeaderView)


def _scan_with_windows_wia(output_path):
    """Open the Windows WIA scanner UI and save one scanned page as PNG."""
    powershell = shutil.which('powershell.exe') or shutil.which('powershell')
    if not powershell:
        raise RuntimeError('Windows PowerShell is required for scanner integration.')

    escaped_output = str(output_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
$dialog = New-Object -ComObject WIA.CommonDialog
$device = $dialog.ShowSelectDevice(1, $true, $false)
if ($null -eq $device) {{ exit 2 }}
$item = $device.Items.Item(1)
$pngFormat = '{{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}}'
$image = $dialog.ShowTransfer($item, $pngFormat, $false)
if ($null -eq $image) {{ exit 2 }}
$image.SaveFile('{escaped_output}')
"""
    encoded_script = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    return subprocess.run(
        [powershell, '-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', encoded_script],
        capture_output=True,
        text=True,
        timeout=600,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        check=False,
    )


def _scanned_image_as_png(path):
    """Normalize scanner-specific BMP/JPEG/PNG output to an actual PNG."""
    image = QImage.fromData(Path(path).read_bytes())
    if image.isNull():
        raise RuntimeError('Windows returned an unsupported or invalid scanner image.')
    buffer = QBuffer()
    if not buffer.open(QIODevice.WriteOnly) or not image.save(buffer, 'PNG'):
        raise RuntimeError('The scanned image could not be converted to PNG.')
    return bytes(buffer.data())


class AttachmentPanel(QWidget):
    CATEGORIES = ['', 'House Pictures', 'Measurements', 'Plans', 'Contracts', 'Kitchen Designs',
                  'Invoices', 'Quotations', 'Installation', 'Maintenance']

    def __init__(self, database, entity_type, entity_id, parent=None):
        super().__init__(parent)
        self.database, self.entity_type, self.entity_id = database, entity_type, int(entity_id)
        self._records = []
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        # The client window now focuses solely on that client's sales. Client
        # attachment controls remain available only in sale attachment dialogs.
        if self.entity_type == 'client':
            self._setup_client_sales(layout)
            self.refresh_sales()
            return
        tools = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText('Search filename or file type…')
        self.search.textChanged.connect(self.refresh)
        self.filter = QComboBox(); self.filter.addItems(['All files', 'Images', 'PDF'])
        self.filter.currentIndexChanged.connect(self.refresh)
        for label, slot in [('Add files', self.add_files), ('Paste image', self.paste_image)]:
            button = QPushButton(label); button.clicked.connect(slot); tools.addWidget(button)
        self.scan_button = QPushButton('Scan document')
        self.scan_button.clicked.connect(self.scan_document)
        self.scan_button.setEnabled(sys.platform == 'win32')
        self.scan_button.setToolTip(
            'Scan one page using a Windows WIA-compatible scanner.'
            if sys.platform == 'win32'
            else 'Direct scanner integration is available only on Windows.'
        )
        tools.addWidget(self.scan_button)
        if self.entity_type == 'sale':
            button = QPushButton('Copy client files'); button.clicked.connect(self.copy_from_client); tools.addWidget(button)
        tools.addWidget(self.search, 1); tools.addWidget(self.filter); layout.addLayout(tools)
        self.table = QTableWidget(0, 5); self.table.setHorizontalHeaderLabels(['Preview', 'Name', 'Type', 'Size', 'Uploaded'])
        self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setIconSize(QSize(150, 150))
        self.table.cellDoubleClicked.connect(lambda *_: self.preview())
        self.table.horizontalHeader().setStretchLastSection(False); layout.addWidget(self.table)
        actions = QHBoxLayout()
        for label, slot in [('Preview', self.preview), ('Open', self.open_selected), ('Export', self.export_selected), ('Print', self.print_selected), ('Rename', self.rename_selected), ('Delete', self.delete_selected)]:
            button = QPushButton(label); button.clicked.connect(slot); actions.addWidget(button)
        actions.addStretch(); layout.addLayout(actions)
        self.client_sales_table = None
        self.client_sales_empty = None
        self.refresh()

    def _setup_client_sales(self, layout):
        self.client_sales_table = None
        sales_label = QLabel('Sales for this client')
        sales_label.setStyleSheet('font-size: 18px; font-weight: bold;')
        layout.addWidget(sales_label)
        self.client_sales_empty = QLabel('No sales found for this client')
        self.client_sales_empty.setAlignment(Qt.AlignCenter)
        self.client_sales_empty.setStyleSheet('color: #9e9e9e; padding: 14px;')
        self.client_sales_table = QTableWidget(0, 6)
        self.client_sales_table.setHorizontalHeaderLabels(['ID', 'Notes', 'Date', 'Subtotal', 'Total', 'Actions'])
        self.client_sales_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.client_sales_table.setEditTriggers(QTableWidget.NoEditTriggers)
        header = self.client_sales_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        for column, width in ((0, 60), (2, 110), (3, 115), (4, 115)):
            self.client_sales_table.setColumnWidth(column, width)
        layout.addWidget(self.client_sales_empty)
        layout.addWidget(self.client_sales_table, 1)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()

    def dropEvent(self, event):
        self._add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]); event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.matches(event.StandardKey.Paste): self.paste_image(); return
        super().keyPressEvent(event)

    def _selected(self):
        ids = {item.row() for item in self.table.selectedItems()}
        return [self._shown[row] for row in sorted(ids)] if hasattr(self, '_shown') else []

    def refresh(self):
        if self.entity_type == 'client':
            self.refresh_sales()
            return
        try: records = self.database.list_attachments(self.entity_type, self.entity_id)
        except Exception as exc: QMessageBox.warning(self, 'Attachments', str(exc)); return
        needle, kind = self.search.text().lower().strip(), self.filter.currentText()
        self._shown = [r for r in records if (not needle or needle in ' '.join(str(r.get(k, '')) for k in ('original_filename','display_name','mime_type')).lower()) and
                       (kind == 'All files' or (kind == 'Images' and str(r['mime_type']).startswith('image/')) or (kind == 'PDF' and r['mime_type'] == 'application/pdf'))]
        self.table.setRowCount(len(self._shown))
        for row, record in enumerate(self._shown):
            preview = QTableWidgetItem('PDF' if record['mime_type'] == 'application/pdf' else '')
            thumbnail = self._thumbnail(record)
            if thumbnail is not None:
                preview.setIcon(QIcon(thumbnail))
            self.table.setItem(row, 0, preview)
            values = [record['display_name'], record['mime_type'].split('/')[-1].upper(), self._size(record['file_size']), str(record['created_at'])[:16]]
            for col, value in enumerate(values, 1): self.table.setItem(row, col, QTableWidgetItem(str(value)))
            # PDFs remain compact; only image rows need room for the preview.
            self.table.setRowHeight(row, 162 if record['mime_type'].startswith('image/') else 46)
        self.table.setColumnWidth(0, 175)
        self.table.setColumnWidth(1, 250)
        self.table.setColumnWidth(2, 95)
        self.table.setColumnWidth(3, 95)
        self.table.setColumnWidth(4, 175)
        # Keep a short list compact instead of leaving a large empty table.
        content_height = self.table.horizontalHeader().height() + sum(
            self.table.rowHeight(row) for row in range(self.table.rowCount())
        ) + 4
        table_height = min(620, max(86, content_height))
        self.table.setMinimumHeight(table_height)
        self.table.setMaximumHeight(table_height)
        host = self.window()
        if self.entity_type != 'client' and isinstance(host, QDialog):
            host.resize(max(host.width(), 900), min(760, table_height + 165))
        if self.entity_type == 'client':
            self.refresh_sales()

    @staticmethod
    def _money(value):
        return f"{float(value or 0):,.2f}".replace(',', ' ')

    @staticmethod
    def _sale_date(value):
        text = str(value or '')
        try:
            from datetime import datetime
            return datetime.strptime(text[:10], '%Y-%m-%d').strftime('%d-%m-%Y')
        except ValueError:
            return text

    def refresh_sales(self):
        """Load only sales whose persisted client_id matches this client."""
        if self.entity_type != 'client' or self.client_sales_table is None:
            return
        self.client_sales_table.setRowCount(0)
        self.client_sales_empty.setVisible(False)
        try:
            sales = self.database.get_client_sales(self.entity_id)
        except Exception as exc:
            QMessageBox.warning(self, 'Client sales', f'Could not load this client\'s sales: {exc}')
            sales = []
        self.client_sales_empty.setVisible(not sales)
        self.client_sales_table.setRowCount(len(sales))
        for row, (sale_id, notes, date, vat, subtotal) in enumerate(sales):
            total = float(subtotal or 0) * (1 + float(vat or 0) / 100)
            for column, value in enumerate((sale_id, notes or '', self._sale_date(date), self._money(subtotal), self._money(total))):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, int(sale_id))
                self.client_sales_table.setItem(row, column, item)
            action_cell = QWidget()
            action_layout = QHBoxLayout(action_cell)
            action_layout.setContentsMargins(4, 2, 4, 2)
            add_button = QPushButton('Add Attachments')
            edit_button = QPushButton('Edit Sale')
            add_button.clicked.connect(lambda _=False, sid=int(sale_id): self.open_sale_attachments(sid))
            edit_button.clicked.connect(lambda _=False, sid=int(sale_id): self.edit_sale(sid))
            action_layout.addWidget(add_button); action_layout.addWidget(edit_button)
            self.client_sales_table.setCellWidget(row, 5, action_cell)
        self.client_sales_table.resizeRowsToContents()

    def open_sale_attachments(self, sale_id):
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Sale #{sale_id} Attachments')
        dialog.resize(950, 620)
        layout = QVBoxLayout(dialog)
        layout.addWidget(AttachmentPanel(self.database, 'sale', int(sale_id), dialog))
        dialog.exec()
        self.refresh_sales()

    def edit_sale(self, sale_id):
        """Reuse the project's live sales editor; never duplicate its form."""
        from ui.tabs.sales_tab import SalesEditDialog
        dialog = SalesEditDialog(int(sale_id), self.database, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh_sales()

    def _thumbnail(self, record):
        if not record['mime_type'].startswith('image/'):
            return None
        try:
            raw = self.database.get_attachment_thumbnail(record['id'])
            image = QImage.fromData(base64.b64decode(raw)) if raw else QImage()
            return QPixmap.fromImage(image) if not image.isNull() else None
        except Exception:
            return None

    @staticmethod
    def _size(value):
        return f'{int(value) / 1024:.1f} KB' if value < 1024 * 1024 else f'{int(value) / 1024 / 1024:.1f} MB'

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Add attachments', '', 'Documents (*.jpg *.jpeg *.png *.webp *.pdf)')
        self._add_paths(paths)

    def _add_paths(self, paths):
        errors = []
        for path in paths:
            try:
                data = Path(path).read_bytes()
                self._upload_bytes(Path(path).name, data)
            except Exception as exc: errors.append(f'{Path(path).name}: {exc}')
        self.refresh()
        if errors: QMessageBox.warning(self, 'Some files were not added', '\n'.join(errors))

    def paste_image(self):
        image = QGuiApplication.clipboard().image()
        if image.isNull(): QMessageBox.information(self, 'Paste image', 'The clipboard does not contain an image.'); return
        data = bytearray(); buffer = QBuffer(); buffer.open(QIODevice.WriteOnly); image.save(buffer, 'PNG')
        try:
            self._upload_bytes('clipboard-image.png', bytes(buffer.data()))
            self.refresh()
        except Exception as exc: QMessageBox.warning(self, 'Paste image', str(exc))

    def _upload_bytes(self, filename, data):
        """Upload to this scope and mirror sale uploads to the linked client."""
        encoded = base64.b64encode(data).decode('ascii')
        self.database.upload_attachment(self.entity_type, self.entity_id, filename, encoded)
        if self.entity_type != 'sale':
            return
        try:
            self.database.cursor.execute(
                'SELECT c.id FROM sales s JOIN clients c ON c.username=s.client_username WHERE s.id=%s',
                (self.entity_id,)
            )
            row = self.database.cursor.fetchone()
            if not row:
                raise ValueError('The sale has no linked client; the file was added only to this sale.')
            self.database.upload_attachment('client', int(row[0]), filename, encoded)
        except Exception as exc:
            # Preserve the successful sale upload while giving a useful action
            # message if old/imported sales are not linked to a client.
            try:
                self.database.conn.rollback()
            except Exception:
                pass
            raise RuntimeError(f'Added to the sale, but could not add it to the client: {exc}') from exc

    def scan_document(self):
        if sys.platform != 'win32':
            QMessageBox.information(
                self,
                'Scan document',
                'Direct scanner integration is currently available only on Windows.',
            )
            return

        try:
            with tempfile.TemporaryDirectory(prefix='pylocalinventory-scan-') as temp_dir:
                scan_path = Path(temp_dir) / 'scan.png'
                result = _scan_with_windows_wia(scan_path)
                if result.returncode == 2:
                    return
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or '').strip()
                    raise RuntimeError(detail or 'Windows could not complete the scan.')
                if not scan_path.is_file() or scan_path.stat().st_size == 0:
                    raise RuntimeError('The scanner completed without producing an image.')

                filename = f"scan-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
                self._upload_bytes(filename, _scanned_image_as_png(scan_path))
            self.refresh()
            QMessageBox.information(self, 'Scan document', 'The scanned page was added successfully.')
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, 'Scan document', 'The scanner did not finish within 10 minutes.')
        except Exception as exc:
            QMessageBox.warning(
                self,
                'Scan document',
                'Unable to scan the document.\n\n'
                f'{exc}\n\n'
                'Make sure the scanner is connected, powered on, and available through Windows Image Acquisition (WIA).',
            )

    def copy_from_client(self):
        """Duplicate chosen permanent client files into the current sale."""
        try:
            # list_attachments has already ensured the migration and cleared a
            # stale failed transaction before this direct sales lookup.
            try:
                self.database.conn.rollback()
            except Exception:
                pass
            self.database.cursor.execute('SELECT id, username, name FROM clients ORDER BY name, username')
            clients = self.database.cursor.fetchall()
        except Exception as exc:
            QMessageBox.warning(self, 'Copy client files', str(exc)); return
        if not clients:
            QMessageBox.information(self, 'Copy client files', 'There are no clients to copy attachments from.')
            return

        # Historical sales can be unlinked, so always provide an explicit
        # client chooser; preselect the sale client when its username matches.
        linked_username = ''
        try:
            self.database.cursor.execute('SELECT client_username FROM sales WHERE id=%s', (self.entity_id,))
            linked = self.database.cursor.fetchone()
            linked_username = str(linked[0] or '') if linked else ''
        except Exception:
            try: self.database.conn.rollback()
            except Exception: pass
        picker = QDialog(self); picker.setWindowTitle('Choose client')
        picker_layout = QVBoxLayout(picker); picker_layout.addWidget(QLabel('Copy permanent attachments from:'))
        client_combo = QComboBox()
        for client_id, username, name in clients:
            client_combo.addItem(f'{name or username} ({username})', int(client_id))
            if username == linked_username:
                client_combo.setCurrentIndex(client_combo.count() - 1)
        picker_layout.addWidget(client_combo)
        picker_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        picker_buttons.accepted.connect(picker.accept); picker_buttons.rejected.connect(picker.reject)
        picker_layout.addWidget(picker_buttons)
        if picker.exec() != QDialog.Accepted:
            return
        records = self.database.list_attachments('client', int(client_combo.currentData()))
        if not records:
            QMessageBox.information(self, 'Copy client files', 'This client has no attachments.')
            return
        chooser = QDialog(self); chooser.setWindowTitle('Select client attachments'); layout = QVBoxLayout(chooser)
        checks = []
        for record in records:
            check = QCheckBox(record['display_name']); check.setChecked(True); layout.addWidget(check); checks.append((check, record))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel); buttons.accepted.connect(chooser.accept); buttons.rejected.connect(chooser.reject); layout.addWidget(buttons)
        if not records or chooser.exec() != QDialog.Accepted: return
        try:
            for check, record in checks:
                if check.isChecked():
                    self.database.upload_attachment('sale', self.entity_id, record['original_filename'], self.database.download_attachment(record['id']), record.get('description',''), record.get('category',''))
            self.refresh()
        except Exception as exc: QMessageBox.warning(self, 'Copy client files', str(exc))

    def _bytes(self, record): return base64.b64decode(self.database.download_attachment(record['id']))

    def preview(self):
        selected = self._selected()
        if not selected: return
        record = selected[0]
        if record['mime_type'] == 'application/pdf': return self.open_selected()
        image = QImage.fromData(self._bytes(record))
        if image.isNull(): return QMessageBox.warning(self, 'Preview', 'This image cannot be previewed.')
        dialog = QDialog(self); dialog.setWindowTitle(record['display_name']); dialog.resize(900, 700)
        label = QLabel(); label.setPixmap(QPixmap.fromImage(image).scaled(850, 650, Qt.KeepAspectRatio, Qt.SmoothTransformation)); label.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea(); scroll.setWidget(label); scroll.setWidgetResizable(True); QVBoxLayout(dialog).addWidget(scroll); dialog.exec()

    def _export(self, record, directory=None):
        target = Path(directory) / record['original_filename'] if directory else None
        if not target:
            filename, _ = QFileDialog.getSaveFileName(self, 'Save attachment', record['original_filename'])
            if not filename: return None
            target = Path(filename)
        target = target.resolve()
        target.write_bytes(self._bytes(record)); return target

    def open_selected(self):
        for record in self._selected():
            path = self._export(record, os.getenv('TEMP') or '.')
            if path: QDesktopServices.openUrl(path.as_uri())

    def export_selected(self):
        for record in self._selected(): self._export(record)

    def print_selected(self):
        for record in self._selected():
            path = self._export(record, os.getenv('TEMP') or '.')
            try: os.startfile(str(path), 'print')
            except Exception as exc: QMessageBox.warning(self, 'Print', f'Could not print {record["display_name"]}: {exc}')

    def rename_selected(self):
        selected = self._selected()
        if len(selected) != 1: return
        record = selected[0]; name, ok = QInputDialog.getText(self, 'Attachment details', 'Display name:', QLineEdit.Normal, record['display_name'])
        if ok and name.strip():
            self.database.update_attachment(record['id'], name.strip()); self.refresh()

    def delete_selected(self):
        selected = self._selected()
        if selected and QMessageBox.question(self, 'Delete attachment', f'Delete {len(selected)} selected attachment(s)?') == QMessageBox.Yes:
            for record in selected: self.database.delete_attachment(record['id'])
            self.refresh()
