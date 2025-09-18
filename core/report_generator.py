#!/usr/bin/env python3
"""
fill_template_qt.py

PySide6 GUI that:
 - connects to a sqlite db,
 - lists deliveries,
 - renders selected delivery into an HTML template (index.html with placeholders),
 - previews inside the app,
 - exports to PDF.

Placeholders expected in index.html:
 {{DATE}}, {{REF}}, {{CLIENT}}, {{ADDRESS}}, {{COMMERCIAL}},
 {{ITEM_ROWS}}, {{TOTAL_ORDERED}}, {{TOTAL_DELIVERED}}, {{REMAIN}}
"""

import sys
import sqlite3
import os
from datetime import datetime
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QMessageBox, QFileDialog
from PySide6.QtGui import QAction

# ------ Configuration ----------
DB_PATH = "inventory.db"         # default sqlite file name (change if needed)
TEMPLATE_PATH = "core/templet.html"  # your template with placeholders
# -------------------------------

def open_db(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite DB not found at: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def try_table_exists(conn, name):
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND lower(name)=?", (name.lower(),))
    return cur.fetchone() is not None

def guess_tables(conn):
    # prefer expected names, otherwise return list of possible tables
    expected = {"deliveries": None, "clients": None, "items": None}
    for t in expected.keys():
        if try_table_exists(conn, t):
            expected[t] = t
    if None in expected.values():
        # fetch all table names
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = [r[0] for r in cur.fetchall()]
        # naive guesses
        for t in all_tables:
            low = t.lower()
            if expected["deliveries"] is None and ("deliver" in low or "bon" in low or "orders" in low):
                expected["deliveries"] = t
            if expected["clients"] is None and ("client" in low or "customer" in low or "company" in low):
                expected["clients"] = t
            if expected["items"] is None and ("item" in low or "line" in low or "product" in low):
                expected["items"] = t
    return expected

def load_delivery_list(conn, tables):
    """
    Return a list of (id, label) for deliveries.
    The query tries to be flexible.
    """
    deliveries_table = tables.get("deliveries")
    if not deliveries_table:
        # fallback: try to take first table
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        row = cur.fetchone()
        if not row:
            return []
        deliveries_table = row[0]

    # Try common column names
    possible_cols = ["id", "delivery_id", "pk"]
    col_name = None
    cur = conn.execute(f"PRAGMA table_info('{deliveries_table}')")
    cols = [r["name"].lower() for r in cur.fetchall()]
    for c in ("id", "pk", "delivery_id"):
        if c in cols:
            col_name = c
            break
    # date/ref heuristics
    date_col = next((c for c in cols if "date" in c), None)
    ref_col = next((c for c in cols if "ref" in c or "reference" in c or "doc" in c), None)
    id_col = col_name or cols[0]

    q = f"SELECT {id_col} AS id, {ref_col or id_col} AS ref, {date_col or 'NULL'} AS date FROM '{deliveries_table}' ORDER BY {id_col} DESC"
    try:
        cur = conn.execute(q)
    except Exception:
        # fallback simple
        cur = conn.execute(f"SELECT rowid as id, * FROM '{deliveries_table}' LIMIT 100")
    items = []
    for r in cur.fetchall():
        ref = r["ref"] if r["ref"] is not None else str(r["id"])
        date = r["date"] if "date" in r.keys() and r["date"] is not None else ""
        label = f"#{r['id']} - {ref} {('('+str(date)+')') if date else ''}"
        items.append((r["id"], label))
    return items

def get_delivery_details(conn, delivery_id, tables):
    """
    Returns dict with header and list of item dicts.
    header: date, ref, client_name, client_address, commercial
    items: list of dicts with code, designation, qty_ordered, qty_delivered
    """
    deliveries_table = tables.get("deliveries")
    items_table = tables.get("items")
    clients_table = tables.get("clients")

    header = {
        "date": "",
        "ref": f"{delivery_id}",
        "client_name": "",
        "client_address": "",
        "commercial": ""
    }
    items = []

    # --- Header fetch ---
    if deliveries_table:
        # try to find useful columns
        cur = conn.execute(f"PRAGMA table_info('{deliveries_table}')")
        cols = [r["name"].lower() for r in cur.fetchall()]
        idcol = next((c for c in cols if c in ("id", "pk", "delivery_id", "rowid")), cols[0])
        datecol = next((c for c in cols if "date" in c), None)
        refcol = next((c for c in cols if "ref" in c or "reference" in c or "doc" in c), None)
        clientcol = next((c for c in cols if "client" in c or "customer" in c), None)
        commercialcol = next((c for c in cols if "commercial" in c or "sales" in c or "commerciale" in c), None)

        q_cols = [idcol]
        if datecol: q_cols.append(datecol)
        if refcol: q_cols.append(refcol)
        if clientcol: q_cols.append(clientcol)
        if commercialcol: q_cols.append(commercialcol)

        q = f"SELECT {', '.join(q_cols)} FROM '{deliveries_table}' WHERE {idcol} = ? LIMIT 1"
        cur = conn.execute(q, (delivery_id,))
        r = cur.fetchone()
        if r:
            if datecol and datecol in r.keys():
                header["date"] = r[datecol] or ""
            if refcol and refcol in r.keys():
                header["ref"] = r[refcol] or header["ref"]
            if commercialcol and commercialcol in r.keys():
                header["commercial"] = r[commercialcol] or ""
            client_key = r[clientcol] if clientcol and clientcol in r.keys() else None
        else:
            client_key = None
    else:
        client_key = None

    # --- Client fetch ---
    if clients_table and client_key is not None:
        # attempt to find client's id column and address/name
        cur = conn.execute(f"PRAGMA table_info('{clients_table}')")
        cs = [r["name"].lower() for r in cur.fetchall()]
        idc = next((c for c in cs if c in ("id", "pk", "client_id", "rowid")), cs[0])
        namec = next((c for c in cs if "name" in c or "company" in c or "raison" in c), None)
        addressc = next((c for c in cs if "address" in c or "adresse" in c or "addr" in c), None)
        try:
            q = f"SELECT {namec or 'NULL'} AS name, {addressc or 'NULL'} AS address FROM '{clients_table}' WHERE {idc} = ? LIMIT 1"
            cur = conn.execute(q, (client_key,))
            r = cur.fetchone()
            if r:
                header["client_name"] = r["name"] or ""
                header["client_address"] = r["address"] or ""
        except Exception:
            pass

    # --- Items fetch ---
    if items_table:
        cur = conn.execute(f"PRAGMA table_info('{items_table}')")
        iscols = [r["name"].lower() for r in cur.fetchall()]
        delivery_fk = next((c for c in iscols if "delivery" in c or "order" in c or "bon" in c), None)
        codecol = next((c for c in iscols if c in ("code", "product_code", "sku")), None)
        desccol = next((c for c in iscols if "design" in c or "designation" in c or "name" in c), None)
        qtyord = next((c for c in iscols if "qty_order" in c or "qty" in c or "ordered" in c or "qte" in c), None)
        qtydel = next((c for c in iscols if "deliv" in c or "delivered" in c or "qty_del" in c or "qte_liv" in c), None)

        if delivery_fk:
            sel = []
            sel.append(codecol or "NULL")
            sel.append(desccol or "NULL")
            sel.append(qtyord or "NULL")
            sel.append(qtydel or "NULL")
            q = f"SELECT {', '.join(sel)} FROM '{items_table}' WHERE {delivery_fk} = ?"
            try:
                cur = conn.execute(q, (delivery_id,))
                rows = cur.fetchall()
                for r in rows:
                    items.append({
                        "code": r[0] or "",
                        "designation": r[1] or "",
                        "qty_ordered": r[2] or 0,
                        "qty_delivered": r[3] or 0
                    })
            except Exception:
                # fallback: return first few rows
                cur = conn.execute(f"SELECT * FROM '{items_table}' LIMIT 10")
                for r in cur.fetchall():
                    items.append({
                        "code": "",
                        "designation": str(dict(r)),
                        "qty_ordered": 0,
                        "qty_delivered": 0
                    })
        else:
            # no delivery_fk — try any rows with matching delivery_id anywhere
            cur = conn.execute(f"SELECT * FROM '{items_table}' LIMIT 10")
            for r in cur.fetchall():
                items.append({
                    "code": "",
                    "designation": str(dict(r)),
                    "qty_ordered": 0,
                    "qty_delivered": 0
                })
    # compute totals
    total_ordered = sum([float(i["qty_ordered"] or 0) for i in items])
    total_delivered = sum([float(i["qty_delivered"] or 0) for i in items])
    remain = total_ordered - total_delivered

    return {
        "header": header,
        "items": items,
        "totals": {"ordered": total_ordered, "delivered": total_delivered, "remain": remain}
    }

def render_html_from_template(template_path, data):
    """
    Load template and replace placeholders with data. Return final HTML string.
    Expects template placeholders described earlier.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError("Template not found: " + template_path)
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()

    header = data["header"]
    totals = data["totals"]
    # create items rows
    rows_html = ""
    if data["items"]:
        for it in data["items"]:
            rows_html += "<tr>\n"
            rows_html += f"  <td>{QtCore.Qt.escape(str(it.get('code','')))}</td>\n"
            rows_html += f"  <td style='text-align:left'>{QtCore.Qt.escape(str(it.get('designation','')))}</td>\n"
            rows_html += f"  <td>{QtCore.Qt.escape(str(it.get('qty_ordered','')))}</td>\n"
            rows_html += f"  <td>{QtCore.Qt.escape(str(it.get('qty_delivered','')))}</td>\n"
            rows_html += "</tr>\n"
    else:
        # put empty rows so the layout looks like the paper
        for _ in range(6):
            rows_html += "<tr><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>\n"

    # Replacements (safe defaults)
    replacements = {
        "{{DATE}}": header.get("date") or "",
        "{{REF}}": header.get("ref") or "",
        "{{CLIENT}}": header.get("client_name") or "",
        "{{ADDRESS}}": (header.get("client_address") or "").replace("\n", "<br>"),
        "{{COMMERCIAL}}": header.get("commercial") or "",
        "{{ITEM_ROWS}}": rows_html,
        "{{TOTAL_ORDERED}}": f"{totals['ordered']:.2f}",
        "{{TOTAL_DELIVERED}}": f"{totals['delivered']:.2f}",
        "{{REMAIN}}": f"{totals['remain']:.2f}"
    }

    for k, v in replacements.items():
        html = html.replace(k, v)

    return html

# ------------------- Qt App -------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, db_path, template_path):
        super().__init__()
        self.setWindowTitle("Delivery Template Filler")
        self.resize(1000, 700)

        # DB + template
        try:
            self.conn = open_db(db_path)
        except Exception as e:
            QMessageBox.critical(self, "DB error", str(e))
            raise

        self.tables = guess_tables(self.conn)
        self.template_path = template_path

        # UI
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        topbar = QtWidgets.QHBoxLayout()
        layout.addLayout(topbar)

        self.combo = QtWidgets.QComboBox()
        topbar.addWidget(QtWidgets.QLabel("Delivery:"))
        topbar.addWidget(self.combo)

        self.btn_load = QtWidgets.QPushButton("Load")
        self.btn_pdf = QtWidgets.QPushButton("Export PDF")
        self.btn_open = QtWidgets.QPushButton("Open in browser")
        topbar.addWidget(self.btn_load)
        topbar.addWidget(self.btn_pdf)
        topbar.addWidget(self.btn_open)

        self.html_view = QtWidgets.QTextBrowser()
        layout.addWidget(self.html_view)

        # load deliveries
        self.populate_deliveries()

        # signals
        self.btn_load.clicked.connect(self.on_load)
        self.btn_pdf.clicked.connect(self.on_export_pdf)
        self.btn_open.clicked.connect(self.on_open_browser)

        # Menu to pick DB / template
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        set_db_act = QAction("Set DB file...", self)
        set_db_act.triggered.connect(self.on_set_db)
        file_menu.addAction(set_db_act)
        set_template_act = QAction("Set template...", self)
        set_template_act.triggered.connect(self.on_set_template)
        file_menu.addAction(set_template_act)
        file_menu.addSeparator()
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        self.current_rendered_html = ""

    def populate_deliveries(self):
        self.combo.clear()
        try:
            items = load_delivery_list(self.conn, self.tables)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not load deliveries: {e}")
            items = []
        for id_, label in items:
            self.combo.addItem(label, id_)

    def on_load(self):
        if self.combo.count() == 0:
            QMessageBox.information(self, "No deliveries", "No deliveries found in DB.")
            return
        delivery_id = self.combo.currentData()
        data = get_delivery_details(self.conn, delivery_id, self.tables)
        html = render_html_from_template(self.template_path, data)
        self.current_rendered_html = html
        self.html_view.setHtml(html)

    def on_export_pdf(self):
        if not self.current_rendered_html:
            QMessageBox.information(self, "No content", "Load a delivery first.")
            return
        fname, _ = QFileDialog.getSaveFileName(self, "Save PDF", "", "PDF Files (*.pdf)")
        if not fname:
            return
        # print to PDF
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(fname)
        # set page size to A4 and margins similar to your template
        printer.setPageSize(QPrinter.PageSize.A4)
        self.html_view.document().print(printer)
        QMessageBox.information(self, "Saved", f"PDF saved to: {fname}")

    def on_open_browser(self):
        # write tmp file and open in system browser
        if not self.current_rendered_html:
            QMessageBox.information(self, "No content", "Load a delivery first.")
            return
        import tempfile, webbrowser
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
        tf.write(self.current_rendered_html)
        tf.close()
        webbrowser.open("file://" + tf.name)

    def on_set_db(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open SQLite DB", "", "SQLite DB (*.db *.sqlite *.sqlite3);;All files (*)")
        if not path:
            return
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = open_db(path)
        self.tables = guess_tables(self.conn)
        self.populate_deliveries()

    def on_set_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open HTML Template", "", "HTML Files (*.html *.htm);;All files (*)")
        if not path:
            return
        self.template_path = path
        QMessageBox.information(self, "Template set", f"Template set to: {path}")

def main():
    app = QtWidgets.QApplication(sys.argv)
    # allow user to pass DB path or template via env / args (optional)
    db = DB_PATH
    tpl = TEMPLATE_PATH
    if len(sys.argv) > 1:
        db = sys.argv[1]
    if len(sys.argv) > 2:
        tpl = sys.argv[2]
    try:
        w = MainWindow(db, tpl)
    except Exception as e:
        print("Failed to start:", e)
        sys.exit(1)
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
