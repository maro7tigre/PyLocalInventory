"""
Client View Dialog - Read-only client information with purchased product history and sales summary
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QWidget, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import GreenButton


class ClientViewDialog(QDialog):
    # Trtib d l-parameters khāṣo y-koun b7al BaseTab: (obj_id, database, parent)
    def __init__(self, client_id, database, parent=None):
        super().__init__(parent)
        
        # 1. Sifet l-data l-asasiya l l-object
        self.database = database
        self.client_id = None
        self.client = None

        # Accept either a client ID, a client dictionary, or a client object
        if isinstance(client_id, dict):
            self.client = client_id
            self.client_id = client_id.get('ID', client_id.get('id'))
        elif hasattr(client_id, 'get_value') or hasattr(client_id, 'id'):
            self.client = client_id
            self.client_id = getattr(client_id, 'id', None)
            if self.client_id is None and hasattr(client_id, 'get_value'):
                self.client_id = client_id.get_value('id')
        else:
            self.client_id = client_id
            if hasattr(self.database, 'get_client_by_id'):
                self.client = self.database.get_client_by_id(client_id)

        self.setWindowTitle("Client Profile & History")
        self.resize(800, 650) # Kberna l-finitra chwya b باش t-hrez l-tabels bjoj
        
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # --- 1. QFrame dyal l-Ma3loumat d l-Klyān ---
        self.info_frame = QFrame()
        self.info_frame.setFrameShape(QFrame.StyledPanel)
        info_layout = QVBoxLayout(self.info_frame)
        
        # N-diro l-Labels
        self.name_label = QLabel()
        self.username_label = QLabel()
        self.type_label = QLabel()
        self.email_label = QLabel()
        self.phone_label = QLabel()
        self.address_label = QLabel()
        self.last_purchase_label = QLabel()
        self.total_purchases_label = QLabel()
        self.sales_count_label = QLabel()
        self.total_sales_label = QLabel()
        self.notes_label = QLabel()
        
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.username_label)
        info_layout.addWidget(self.type_label)
        info_layout.addWidget(self.email_label)
        info_layout.addWidget(self.phone_label)
        info_layout.addWidget(self.address_label)
        info_layout.addWidget(self.last_purchase_label)
        info_layout.addWidget(self.total_purchases_label)
        info_layout.addWidget(self.sales_count_label)
        info_layout.addWidget(self.total_sales_label)
        info_layout.addWidget(self.notes_label)
        
        layout.addWidget(self.info_frame)
        
        # --- 2. Sales History (Invoices) ---
        layout.addWidget(QLabel("<h3>Sales History (Invoices)</h3>"))
        self.sales_table = QTableWidget()
        self.sales_table.setColumnCount(4)
        self.sales_table.setHorizontalHeaderLabels(["Sale ID", "Date", "Total Invoice", "Status"])
        self.sales_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.sales_table)
        
        # --- 4. Button d l-Ghlela (Close) ---
        button_row = QHBoxLayout()
        button_row.addStretch()
        close_btn = GreenButton("Close")
        close_btn.setFixedSize(120, 36)
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)
        
        # --- 5. Chargement dyal l-Data ---
        self.load_client_info()
        self.load_client_sales()
        self.apply_theme()

    def load_client_info(self):
        # Ila l-client jbnaeh ghadin n-3mro l-wajiha
        if not self.client:
            self.name_label.setText(f"ID: {self.client_id} (No additional object info found)")
            return
            
        # 3la ḥsab l-class dyalk kifach kay-jbed l-values
        if hasattr(self.client, 'get_value'):
            self.name_label.setText(f"Name: {self.client.get_value('name') or '—'}")
            self.username_label.setText(f"Username: {self.client.get_value('username') or '—'}")
            self.type_label.setText(f"Type: {self.client.get_value('client_type') or '—'}")
            self.email_label.setText(f"Email: {self.client.get_value('email') or '—'}")
            self.phone_label.setText(f"Phone: {self.client.get_value('phone') or '—'}")
            self.address_label.setText(f"Address: {self.client.get_value('address') or '—'}")
            self.notes_label.setText(f"Notes: {self.client.get_value('notes') or 'None'}")
        else:
            # Ila kan single dict mn database directly
            self.name_label.setText(f"Name: {self.client.get('name', '—')}")
            self.username_label.setText(f"Username: {self.client.get('username', '—')}")
            self.type_label.setText(f"Type: {self.client.get('client_type', '—')}")
            self.email_label.setText(f"Email: {self.client.get('email', '—')}")
            self.phone_label.setText(f"Phone: {self.client.get('phone', '—')}")
            self.address_label.setText(f"Address: {self.client.get('address', '—')}")
            self.notes_label.setText(f"Notes: {self.client.get('notes', 'None')}")

        last_date = self.client.get_last_purchase_date() if hasattr(self.client, 'get_last_purchase_date') else None
        total = self.client.get_total_purchases() if hasattr(self.client, 'get_total_purchases') else 0.0

        self.last_purchase_label.setText(f"Last Purchase: {last_date or 'No purchases yet'}")
        self.total_purchases_label.setText(f"Total Purchases: {total:.2f} MAD")
        self.sales_count_label.setText("Sales Count: 0")
        self.total_sales_label.setText("Sales Total: 0.00 MAD")


    def load_client_sales(self):
        """Khāṣa b باش t-byen l-faytonat kamlin (Sales Summary)"""
        sales_list = []
        try:
            if self.database and getattr(self.database, 'cursor', None):
                # Prefer the database helper, but support direct fallback for legacy tables
                if hasattr(self.database, 'get_sales_by_client'):
                    sales_list = self.database.get_sales_by_client(self.client_id)
                else:
                    self.database.cursor.execute(
                        "SELECT ID, date, total_price, state FROM Sales WHERE client_id = ? ORDER BY date DESC, ID DESC",
                        (self.client_id,)
                    )
                    rows = self.database.cursor.fetchall() or []
                    columns = [description[0] for description in self.database.cursor.description]
                    sales_list = [dict(zip(columns, row)) for row in rows]
        except Exception as e:
            print(f"Error loading client invoices: {e}")
        
        self.sales_table.setRowCount(0)
        for row_number, sale in enumerate(sales_list):
            self.sales_table.insertRow(row_number)
            
            # Khroj l-data b dynamic checks (3la hseb column case-sensitivity f sqlite)
            sale_id = str(sale.get('ID', sale.get('id', '')))
            sale_date = str(sale.get('date', ''))
            total = float(sale.get('total_price', sale.get('total_amount', 0) or 0))
            status = str(sale.get('state', sale.get('status', 'pending')))
            
            item_id = QTableWidgetItem(sale_id)
            item_date = QTableWidgetItem(sale_date)
            item_total = QTableWidgetItem(f"{total:.2f} MAD")
            item_status = QTableWidgetItem(status)
            
            for item in [item_id, item_date, item_total, item_status]:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

            self.sales_table.setItem(row_number, 0, item_id)
            self.sales_table.setItem(row_number, 1, item_date)
            self.sales_table.setItem(row_number, 2, item_total)
            self.sales_table.setItem(row_number, 3, item_status)

        if not sales_list:
            self.sales_table.setRowCount(1)
            item = QTableWidgetItem("No invoices found for this client")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.sales_table.setItem(0, 0, item)
            self.sales_table.setSpan(0, 0, 1, self.sales_table.columnCount())
            self.sales_count_label.setText("Sales Count: 0")
            self.total_sales_label.setText("Sales Total: 0.00 MAD")
        else:
            self.sales_count_label.setText(f"Sales Count: {len(sales_list)}")
            total_sales = sum(float(sale.get('total_price', sale.get('total_amount', 0) or 0) or 0) for sale in sales_list)
            self.total_sales_label.setText(f"Sales Total: {total_sales:.2f} MAD")

    def apply_theme(self):
        self.setStyleSheet("""
            QDialog { background-color: #1f1f1f; color: #ffffff; }
            QLabel { color: #ffffff; font-size: 13px; }
            QFrame { border: 1px solid #3b3b3b; border-radius: 6px; padding: 10px; background-color: #252525; }
            QTableWidget { background-color: #1a1a1a; color: #ffffff; gridline-color: #333333; border: 1px solid #333333; }
            QHeaderView::section { background-color: #2b2b2b; color: #ffffff; border: 1px solid #333333; font-weight: bold; padding: 5px; }
            QTableWidget::item:selected { background-color: #2e7d32; color: white; }
        """)