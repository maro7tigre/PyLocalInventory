import sys
import re

with open('ui/dialogs/client_details_dialog.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Fix _create_table to use Interactive instead of ResizeToContents
# We'll set the stretch elsewhere.
create_table_replacement = """    def _create_table(self, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        # Ensure rows aren't too cramped
        table.verticalHeader().setDefaultSectionSize(40)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        # Add basic styling to headers
        table.setStyleSheet("QHeaderView::section { font-weight: bold; padding: 4px; }")
        return table"""

code = re.sub(r'    def _create_table\(self, headers\):.*?return table', create_table_replacement, code, flags=re.DOTALL)

# Now we need to set the specific column widths and alignments for Purchases table
# Let's find _compute_purchases

# For Purchases table columns:
# 0: Sale (Center)
# 1: Date (Left)
# 2: Product / Service (Left, Stretch)
# 3: Quantity (Center)
# 4: Unit Price (Right)
# 5: State (Center)
# 6: Total (Right)
# 7: Paid (Right)
# 8: Remaining (Right)

# And for Payment History:
# 0: Payment ID (Center)
# 1: Sale (Center)
# 2: Date (Left)
# 3: Amount (Right)
# 4: Purchase (Left, Stretch)

# I'll inject the column width logic into _setup_ui right after creating the tables
setup_ui_table_fix = """
        self.purchases_table = self._create_table(
            [
                "Sale",
                "Date",
                "Product / Service",
                "Quantity",
                "Unit Price",
                "State",
                "Total",
                "Paid",
                "Remaining",
            ]
        )
        self.purchases_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.purchases_table.setColumnWidth(0, 80)
        self.purchases_table.setColumnWidth(1, 100)
        self.purchases_table.setColumnWidth(3, 80)
        self.purchases_table.setColumnWidth(4, 100)
        self.purchases_table.setColumnWidth(5, 100)
        self.purchases_table.setColumnWidth(6, 100)
        self.purchases_table.setColumnWidth(7, 100)
        self.purchases_table.setColumnWidth(8, 100)
"""
code = re.sub(r'\s*self.purchases_table = self._create_table\([\s\S]*?\]\s*\)', setup_ui_table_fix, code)

setup_ui_payment_fix = """
        self.payments_table = self._create_table(
            ["Payment", "Sale", "Date", "Amount", "Purchase"]
        )
        self.payments_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.payments_table.setColumnWidth(0, 80)
        self.payments_table.setColumnWidth(1, 80)
        self.payments_table.setColumnWidth(2, 120)
        self.payments_table.setColumnWidth(3, 120)
"""
code = re.sub(r'\s*self.payments_table = self._create_table\([\s\S]*?\]\s*\)', setup_ui_payment_fix, code)

# Let's also fix text alignments in `_compute_purchases` and `_compute_payments`
alignments_purchases = """
            item_id.setTextAlignment(Qt.AlignCenter)
            item_date.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_prod.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_qty.setTextAlignment(Qt.AlignCenter)
            item_price.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_state.setTextAlignment(Qt.AlignCenter)
            item_total.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_paid.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_rem.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            # Subtle visual grouping for same Sale IDs
            if i > 0 and self.purchases[i]['sale_id'] == self.purchases[i-1]['sale_id']:
                item_id.setForeground(QBrush(QColor("#777777")))
                item_date.setForeground(QBrush(QColor("#777777")))
            
            self.purchases_table.setItem(i, 0, item_id)
"""
code = re.sub(r'\s*self.purchases_table.setItem\(i, 0, item_id\)', alignments_purchases, code)

alignments_payments = """
            item_id.setTextAlignment(Qt.AlignCenter)
            item_sale.setTextAlignment(Qt.AlignCenter)
            item_date.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            item_amount.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_desc.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            self.payments_table.setItem(i, 0, item_id)
"""
code = re.sub(r'\s*self.payments_table.setItem\(i, 0, item_id\)', alignments_payments, code)

with open('ui/dialogs/client_details_dialog.py', 'w', encoding='utf-8') as f:
    f.write(code)
