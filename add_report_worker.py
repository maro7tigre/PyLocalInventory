import sys

with open('ui/dialogs/client_details_dialog.py', 'r', encoding='utf-8') as f:
    code = f.read()

worker_code = """
import os
import tempfile
import html
import time
from pathlib import Path
from ui.dialogs.reports_dialog import ReportsDialog
from core.runtime_paths import resource_path

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
            
            output_dir = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Documents", "PyLocalInventory", "Reports")
            os.makedirs(output_dir, exist_ok=True)
            
            # Use timestamp
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"ClientStatement_{timestamp}.pdf" if self.report_type == 'full_statement' else f"SaleReport_{self.selected_sale_id}_{timestamp}.pdf"
            output_path = os.path.join(output_dir, filename)
            
            # Delegate to existing HTML to PDF logic
            # We can instantiate ReportsDialog safely by passing None for sales_obj
            dialog = ReportsDialog(None, None, None)
            dialog._html_to_pdf(html_content, output_path)
            
            self.finished.emit(output_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.failed.emit(str(e))

    def _fmt_money(self, val):
        return f"{float(val or 0):,.2f}".replace(",", " ")

    def _generate_html(self):
        template_path = resource_path("report", "client_statement_templet.html")
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
            
        data = {
            "report_title": "Relevé de Compte" if self.report_type == 'full_statement' else f"Détails de la Vente #{self.selected_sale_id}",
            "date": time.strftime("%d-%m-%Y"),
            "client_name": html.escape(str(self.client_data.get('name') or self.client_data.get('username') or '')),
            "client_details": f"ID: {self.client_data.get('id', '')}<br>ICE: {html.escape(str(self.client_data.get('ice') or ''))}<br>Tel: {html.escape(str(self.client_data.get('phone') or ''))}",
            "logo_block": ReportsDialog(None, None, None)._get_lamidap_logo_block(),
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
        
        # We can dynamically inject company info if available via some global config, but the existing report logic relies on settings.
        # Let's try to grab settings if possible, otherwise leave defaults.
        try:
            from core.settings import SettingsManager
            settings = SettingsManager()
            data["company_name"] = html.escape(settings.get_setting("Company", "name", "My Company"))
            data["company_address"] = html.escape(settings.get_setting("Company", "address", "")).replace('\\n', '<br>')
            data["company_phone"] = html.escape(settings.get_setting("Company", "phone", ""))
            data["company_email"] = html.escape(settings.get_setting("Company", "email", ""))
        except:
            pass

        # Filter purchases
        if self.report_type == 'selected_sale':
            sales_purchases = [p for p in self.purchases if p['sale_id'] == self.selected_sale_id]
        else:
            sales_purchases = self.purchases
            
        # Group by sale
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
        
        # Sort sales by ID
        for sale_id in sorted(sales.keys()):
            sale_data = sales[sale_id]
            s_info = sale_data['info']
            global_total += sale_data['total']
            global_paid += sale_data['paid']
            
            # Sale header
            items_html += f"<div class='items-block'>"
            items_html += f"<div class='sale-header'>Vente #{sale_id} - Date: {s_info['date']} - Statut: {s_info['state'].replace('_', ' ').title()}</div>"
            
            if s_info.get('sale_info'):
                items_html += f"<div style='font-size:11px; margin-bottom:5px;'>Notes: {html.escape(str(s_info['sale_info']))}</div>"
                
            items_html += "<table><thead><tr><th>Type</th><th>Produit/Service</th><th>Qté</th><th>P.U</th><th>Total</th></tr></thead><tbody>"
            
            # Items
            for item in sale_data['items']:
                name = html.escape(str(item['product']))
                if item.get('item_info'):
                    name += f"<br><span class='item-detail'>{html.escape(str(item['item_info']))}</span>"
                
                subtotal = float(item['quantity']) * float(item['unit_price'])
                items_html += f"<tr><td>{item.get('item_type', 'Product')}</td><td style='text-align:left;'>{name}</td><td>{item['quantity']}</td><td>{self._fmt_money(item['unit_price'])}</td><td>{self._fmt_money(subtotal)}</td></tr>"
            
            # Totals row for sale
            remise = float(sale_data['remise'])
            items_html += f"<tr><td colspan='4' style='text-align:right; font-weight:bold;'>Remise:</td><td style='font-weight:bold;'>{self._fmt_money(remise)}</td></tr>"
            items_html += f"<tr><td colspan='4' style='text-align:right; font-weight:bold;'>Total TTC:</td><td style='font-weight:bold;'>{self._fmt_money(sale_data['total'])}</td></tr>"
            items_html += "</tbody></table>"
            
            # Payments for this sale
            sale_payments = [pay for pay in self.payments if pay[1] == sale_id]
            if sale_payments:
                items_html += "<table class='payments-table'><thead><tr><th>Date Paiement</th><th>Montant</th></tr></thead><tbody>"
                for pay in sale_payments:
                    items_html += f"<tr><td>{pay[3]}</td><td style='text-align:right; color:green;'>{self._fmt_money(pay[4])}</td></tr>"
                items_html += "</tbody></table>"
                
            items_html += f"<div style='text-align:right; font-size:11px; font-weight:bold; margin-bottom:15px;'>Reste à payer (Vente #{sale_id}): <span style='color:red;'>{self._fmt_money(sale_data['total'] - sale_data['paid'])}</span></div>"
            items_html += "</div>"
            
        data["items"] = items_html
        data["total_bought"] = self._fmt_money(global_total)
        data["total_paid"] = self._fmt_money(global_paid)
        data["total_remaining"] = self._fmt_money(max(0, global_total - global_paid))
        
        # Replace
        for k, v in data.items():
            template = template.replace('{{ ' + k + ' }}', str(v))
            
        return template
"""

if "class _ClientReportWorker" not in code:
    code = code.replace("class ClientDetailsDialog(QDialog):", worker_code + "\n\nclass ClientDetailsDialog(QDialog):")
    with open('ui/dialogs/client_details_dialog.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("Worker added.")
else:
    print("Worker already exists.")
