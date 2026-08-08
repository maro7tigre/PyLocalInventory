import re

with open('ui/dialogs/client_details_dialog.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Restore _ClientAccountWorker.run and replace the incorrect block
account_worker_original = """    @Slot()
    def run(self):
        try:
            account_data = self.database.get_client_account(self.client_id)
            self.finished.emit(account_data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))"""

client_report_worker_class = """
class _ClientReportWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, report_type, client_data, purchases, payments, selected_sale_id=None):
        super().__init__()
        self.report_type = report_type
        self.client_data = client_data
        self.purchases = purchases
        self.payments = payments
        self.selected_sale_id = selected_sale_id

    @Slot()
    def run(self):
        try:
            html_content = self._generate_html()
            
            import os
            import time
            output_dir = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Documents", "PyLocalInventory", "Reports")
            os.makedirs(output_dir, exist_ok=True)
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"ClientStatement_{timestamp}.pdf" if self.report_type == 'full_statement' else f"SaleReport_{self.selected_sale_id}_{timestamp}.pdf"
            output_path = os.path.join(output_dir, filename)
            
            self._html_to_pdf(html_content, output_path)
            
            self.finished.emit(output_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))

    def _html_to_pdf(self, html_content, output_path):
        import tempfile
        import os
        from pathlib import Path
        from ui.dialogs.reports_dialog import ReportsDialog
        from core.runtime_paths import resource_path
        temp_html_path = None
        try:
            base_url = os.path.abspath(resource_path("report"))
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_html:
                temp_html.write(html_content)
                temp_html_path = temp_html.name
            from playwright.sync_api import sync_playwright
            executable = ReportsDialog._find_installed_chromium()
            if not executable:
                raise FileNotFoundError("The bundled Chromium PDF engine is missing.")
            
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
                raise RuntimeError("PDF generation produced an empty or missing file.")
        finally:
            if temp_html_path and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                except:
                    pass

    def _get_lamidap_logo_block(self):
        import os
        import base64
        from core.runtime_paths import resource_path
        logo_path = resource_path('report', 'lamidap_logo.png')
        if not os.path.isfile(logo_path):
            raise FileNotFoundError(f"Required report logo is missing: {logo_path}")
        with open(logo_path, 'rb') as img_f:
            b64 = base64.b64encode(img_f.read()).decode('ascii')
        return (
            f'<img src="data:image/png;base64,{b64}" '
            f'class="report-logo" width="120" '
            f'style="width: 120px; height: auto; max-height: 80px; object-fit: contain; display: block; margin: 0 0 6px 0;" />'
        )

    def _fmt_money(self, val):
        return f"{float(val or 0):,.2f}".replace(",", " ")

    def _generate_html(self):
        import time
        import html
        from core.runtime_paths import resource_path
        template_path = resource_path("report", "client_statement_templet.html")
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
            
        data = {
            "report_title": "Relevé de Compte" if self.report_type == 'full_statement' else f"Détails de la Vente #{self.selected_sale_id}",
            "date": time.strftime("%d-%m-%Y"),
            "client_name": html.escape(str(self.client_data.get('name') or self.client_data.get('username') or '')),
            "client_details": f"ID: {self.client_data.get('id', '')}<br>ICE: {html.escape(str(self.client_data.get('ice') or ''))}<br>Tel: {html.escape(str(self.client_data.get('phone') or ''))}",
            "logo_block": self._get_lamidap_logo_block(),
            "company_name": "My Company", # fallback
            "company_address": "",
            "company_phone": "",
            "company_email": "",
            "report_footer": "Généré par PyLocalInventory",
            "items": "",
            "total_bought": "0.00",
            "total_paid": "0.00",
            "total_remaining": "0.00"
        }
        
        try:
            from core.settings import SettingsManager
            settings = SettingsManager()
            data["company_name"] = html.escape(settings.get_setting("Company", "name", "My Company"))
            data["company_address"] = html.escape(settings.get_setting("Company", "address", "")).replace('\n', '<br>')
            data["company_phone"] = html.escape(settings.get_setting("Company", "phone", ""))
            data["company_email"] = html.escape(settings.get_setting("Company", "email", ""))
        except:
            pass

        if self.report_type == 'selected_sale':
            sales_purchases = [p for p in self.purchases if p['sale_id'] == self.selected_sale_id]
        else:
            sales_purchases = self.purchases
            
        sales = {}
        for p in sales_purchases:
            if p['sale_id'] not in sales:
                sales[p['sale_id']] = {
                    'info': p,
                    'items': [],
                    'total': 0.0,
                    'paid': 0.0,
                    'remise': p.get('remise', 0.0)
                }
            sales[p['sale_id']]['items'].append(p)
            sales[p['sale_id']]['total'] += float(p['total'])
            sales[p['sale_id']]['paid'] += float(p['paid'])
            
        items_html = ""
        global_total = 0.0
        global_paid = 0.0
        
        for sale_id in sorted(sales.keys()):
            sale_data = sales[sale_id]
            s_info = sale_data['info']
            global_total += sale_data['total']
            global_paid += sale_data['paid']
            
            items_html += f"<div class='items-block'>"
            items_html += f"<div class='sale-header'>Vente #{sale_id} - Date: {s_info['date']} - Statut: {s_info['state'].replace('_', ' ').title()}</div>"
            items_html += f"<table class='items-table'><thead><tr><th>Type</th><th>Produit/Service</th><th>Qté</th><th>Prix U.</th><th>S/Total</th></tr></thead><tbody>"
            
            sale_subtotal = 0.0
            for item in sale_data['items']:
                st = float(item['total'])
                sale_subtotal += st
                items_html += f"<tr><td>{item['item_type'].title()}</td><td>{html.escape(item['product'])}</td><td>{item['qty']}</td><td>{self._fmt_money(item['unit_price'])}</td><td>{self._fmt_money(st)}</td></tr>"
            
            items_html += "</tbody></table>"
            items_html += f"<div class='totals-block'>"
            items_html += f"<div><span class='totals-label'>Total Vente:</span> <span class='totals-value'>{self._fmt_money(sale_data['total'])} MAD</span></div>"
            if sale_data['paid'] > 0:
                items_html += f"<div><span class='totals-label'>Total Payé:</span> <span class='totals-value'>{self._fmt_money(sale_data['paid'])} MAD</span></div>"
                items_html += f"<div><span class='totals-label'>Reste à Payer:</span> <span class='totals-value'>{self._fmt_money(sale_data['total'] - sale_data['paid'])} MAD</span></div>"
            items_html += "</div></div>"
            
        data["items"] = items_html
        data["total_bought"] = self._fmt_money(global_total)
        data["total_paid"] = self._fmt_money(global_paid)
        data["total_remaining"] = self._fmt_money(global_total - global_paid)
        
        for k, v in data.items():
            template = template.replace(f"{{{{{k}}}}}", str(v))
            
        return template
"""

# Use regex to find `class _ClientAccountWorker` block up to `class ClientDetailsDialog`
match = re.search(r'(class _ClientAccountWorker\(QObject\):.*?    @Slot\(\)).*?(?=class ClientDetailsDialog\(QDialog\):)', code, re.DOTALL)
if match:
    new_block = match.group(1) + "\n" + account_worker_original + "\n\n" + client_report_worker_class + "\n\n"
    code = code[:match.start()] + new_block + code[match.end():]

with open('ui/dialogs/client_details_dialog.py', 'w', encoding='utf-8') as f:
    f.write(code)
