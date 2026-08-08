import sys
with open('ui/dialogs/client_details_dialog.py', 'r', encoding='utf-8') as f:
    code = f.read()
code = code.replace("purchases_layout.addWidget(purchases_title)", """
        purchases_title = QLabel("Purchases")
        purchases_title.setStyleSheet("font-size:16px; font-weight:bold;")
        purchases_layout.addWidget(purchases_title)
""")
with open('ui/dialogs/client_details_dialog.py', 'w', encoding='utf-8') as f:
    f.write(code)
