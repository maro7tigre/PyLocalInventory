"""
Reports Dialog - For selecting report type and generating PDF reports
"""
import os
import sys
import glob
import subprocess
import tempfile
import shutil
from datetime import datetime, timedelta
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QMessageBox, QApplication)
from PySide6.QtCore import Qt
from ui.widgets.themed_widgets import BlueButton, RedButton
import base64


class ReportsDialog(QDialog):
    """Dialog for selecting and generating reports"""
    
    def __init__(self, sales_obj, profile_manager, parent=None):
        super().__init__(parent)
        self.sales_obj = sales_obj
        self.profile_manager = profile_manager
        self.setWindowTitle("Generate Report")
        self.setModal(True)
        self.resize(400, 200)
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("Select Report Type")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Sales info
        if self.sales_obj:
            client_name = self.sales_obj.get_value('client_name') or 'Unknown Client'
            date = self.sales_obj.get_value('date') or 'Unknown Date'
            info_label = QLabel(f"Client: {client_name}\nDate: {date}")
            info_label.setStyleSheet("color: #cccccc; text-align: center;")
            info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(info_label)
        
        # Report type buttons
        buttons_layout = QHBoxLayout()
        self.devis_btn = BlueButton("Devis")
        self.devis_btn.clicked.connect(lambda: self.generate_report("devis"))
        buttons_layout.addWidget(self.devis_btn)

        self.facture_btn = BlueButton("Facture")
        self.facture_btn.clicked.connect(lambda: self.generate_report("facture"))
        buttons_layout.addWidget(self.facture_btn)
        
        layout.addLayout(buttons_layout)
        
        # Cancel button
        cancel_layout = QHBoxLayout()
        cancel_layout.addStretch()
        
        self.cancel_btn = RedButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        cancel_layout.addWidget(self.cancel_btn)
        
        layout.addLayout(cancel_layout)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
                background-color: transparent;
            }
        """)
    
    def generate_report(self, report_type):
        """Generate report of specified type"""
        try:
            # Gate facture generation to confirmed sales
            if report_type == 'facture':
                state = self.sales_obj.get_value('state') if self.sales_obj else None
                if state != 'confirmed':
                    QMessageBox.warning(self, "Not Confirmed", "You can only generate a facture for a confirmed sale.")
                    return
            # Disable buttons during generation
            self.devis_btn.setEnabled(False)
            self.facture_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            
            # Show progress
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            
            # Generate report directly
            pdf_path = self._generate_report_sync(report_type)
            
            # Restore cursor and enable buttons
            QApplication.restoreOverrideCursor()
            self.devis_btn.setEnabled(True)
            self.facture_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            
            # Handle success - show message but don't close dialog
            QMessageBox.information(self, "Success", f"Report generated successfully!\n\nSaved to: {pdf_path}")
            
            # Open the generated file
            try:
                self.open_pdf(pdf_path)
            except Exception as e:
                QMessageBox.warning(self, "Warning", f"Report generated but failed to open:\n{str(e)}")
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.devis_btn.setEnabled(True)
            self.facture_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            QMessageBox.critical(self, "Error", f"Failed to generate report:\n{str(e)}")
    
    def _generate_report_sync(self, report_type):
        """Synchronously generate report and return PDF path"""
        # Get current profile path
        if not self.profile_manager.selected_profile:
            raise Exception("No profile selected")
        
        profile_path = os.path.dirname(self.profile_manager.selected_profile.config_path)
        reports_dir = os.path.join(profile_path, "reports")
        
        # Create reports directory if it doesn't exist
        os.makedirs(reports_dir, exist_ok=True)
        
        # Clean up old reports (older than 2 days)
        self._cleanup_old_reports(reports_dir)
        
        # Generate unique filename
        date_str = datetime.now().strftime("%d_%m_%Y")
        counter = 0
        while True:
            filename = f"{date_str}_{counter}.pdf"
            filepath = os.path.join(reports_dir, filename)
            if not os.path.exists(filepath):
                break
            counter += 1
        
        # Generate HTML content
        html_content = self._generate_html_content(report_type)
        
        # Convert HTML to PDF (or HTML fallback)
        actual_output_path = self._html_to_pdf(html_content, filepath)
        
        return actual_output_path
    
    def _cleanup_old_reports(self, reports_dir):
        """Delete reports older than 2 days"""
        cutoff_date = datetime.now() - timedelta(days=2)
        
        for pdf_file in glob.glob(os.path.join(reports_dir, "*.pdf")):
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(pdf_file))
                if file_mtime < cutoff_date:
                    os.remove(pdf_file)
            except Exception as e:
                print(f"Error deleting old report {pdf_file}: {e}")
    
    def _generate_html_content(self, report_type):
        """Generate HTML content based on report type"""
        # Get template path
        # Map facture to devis template (same layout with label replacement)
        mapped = 'devis' if report_type == 'facture' else report_type
        template_path = os.path.join("report", f"{mapped}_templet.html")
        
        if not os.path.exists(template_path):
            raise Exception(f"Template file not found: {template_path}")
        
        # Read template
        with open(template_path, 'r', encoding='utf-8') as f:
            template_content = f.read()
        
        # Get sales data
        sales_data = self._extract_sales_data(report_type)
        
        # Replace placeholders
        html_content = self._replace_placeholders(template_content, sales_data)
        # If facture, replace visible title text
        if report_type == 'facture':
            html_content = html_content.replace('<h2>Devis</h2>', '<h2>Facture</h2>')
            html_content = html_content.replace('<title>Devis</title>', '<title>Facture</title>')
        
        return html_content
    
    def _extract_sales_data(self, report_type: str):
        """Extract data from sales object"""
        try:
            def _fmt_fr(value: float) -> str:
                try:
                    s = f"{float(value):,.2f}"
                    # Convert 1,234.56 -> 1.234,56
                    return s.replace(',', 'X').replace('.', ',').replace('X', '.')
                except Exception:
                    return str(value)

            # Get profile data
            profile = self.profile_manager.selected_profile
            company_name = profile.get_value("company name") or "Your Company"
            company_phone = profile.get_value("phone") or ""
            company_address = profile.get_value("address") or ""
            company_email = profile.get_value("email") or ""
            report_footer = profile.get_value("report footer") or ""

            # Build logo block from profile preview if available
            logo_block = '<div class="logo-placeholder">LOGO</div>'
            try:
                preview_path = getattr(profile, 'preview_path', None)
                if preview_path and os.path.exists(preview_path):
                    # Read and encode image as base64 data URI (supports png/jpg)
                    ext = os.path.splitext(preview_path)[1].lower()
                    mime = 'image/png' if ext in ['.png'] else ('image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png')
                    with open(preview_path, 'rb') as img_f:
                        b64 = base64.b64encode(img_f.read()).decode('ascii')
                    # Constrain displayed logo size via inline style to fit header nicely
                    logo_block = (
                        f'<img src="data:{mime};base64,{b64}" '
                        f'style="max-width: 200px; max-height: 80px; object-fit: contain; display: block; margin-bottom: 4px;" />'
                    )
            except Exception as _e:
                # Fallback to placeholder on any issue
                logo_block = '<div class="logo-placeholder">LOGO</div>'

            # Extract sales data
            client_username = self.sales_obj.get_value('client_username') or ""
            client_name = self.sales_obj.get_value('client_name') or ""
            date = self.sales_obj.get_value('date') or datetime.now().strftime("%d-%m-%Y")
            total_price = self.sales_obj.get_value('total_price') or 0
            
            # Generate document reference
            sales_id = self.sales_obj.get_value('id') or self.sales_obj.get_value('ID') or 1
            facture_number = self.sales_obj.get_value('facture_number') or None
            if report_type == 'facture' and facture_number:
                doc_ref = f"FAC-{int(facture_number):06d}"
            else:
                doc_ref = f"DOC-{sales_id:06d}"
            
            # Get sales items - ensure they are loaded from database
            items_html = ""
            total_quantity = 0
            
            # Load sales items if not already loaded
            if not hasattr(self.sales_obj, 'items') or not self.sales_obj.items:
                print("DEBUG: Loading sales items from database...")
                sales_id_value = self.sales_obj.get_value('id') or self.sales_obj.get_value('ID')
                if sales_id_value and hasattr(self.sales_obj, 'database') and self.sales_obj.database:
                    try:
                        # Load items from database
                        items_data = self.sales_obj.database.get_items_by_operation_id(sales_id_value, 'Sales_Items')
                        print(f"DEBUG: Found {len(items_data)} sales items in database")
                        
                        # Create item objects
                        from classes.sales_item_class import SalesItemClass
                        self.sales_obj.items = []
                        for item_data in items_data:
                            item_obj = SalesItemClass(0, self.sales_obj.database)
                            # Load item data
                            for key, value in item_data.items():
                                if key in item_obj.parameters:
                                    try:
                                        item_obj.set_value(key, value)
                                    except:
                                        pass
                            self.sales_obj.items.append(item_obj)
                    except Exception as e:
                        print(f"DEBUG: Error loading sales items: {e}")
            
            devis_rows = []  # rows for devis/facture full-table rendering
            if hasattr(self.sales_obj, 'items') and self.sales_obj.items:
                print(f"DEBUG: Processing {len(self.sales_obj.items)} sales items")
                total_ht = 0
                for item in self.sales_obj.items:
                    product_name = item.get_value('product_name') or ""
                    
                    # If product_name is empty, try to get it from product_id
                    if not product_name:
                        product_id = item.get_value('product_id')
                        if product_id and hasattr(self.sales_obj, 'database') and self.sales_obj.database:
                            try:
                                # Get product name from Products table
                                product_data = self.sales_obj.database.cursor.execute(
                                    "SELECT name FROM Products WHERE ID = ?", (product_id,)
                                ).fetchone()
                                if product_data:
                                    product_name = product_data[0]
                            except Exception as e:
                                print(f"DEBUG: Error getting product name: {e}")
                    
                    quantity = item.get_value('quantity') or 0
                    unit_price = item.get_value('unit_price') or 0
                    subtotal = item.get_value('subtotal') or (quantity * unit_price)
                    
                    print(f"DEBUG: Item - Product: {product_name}, Qty: {quantity}, Price: {unit_price}")
                    
                    total_quantity += int(quantity) if quantity else 0
                    total_ht += float(subtotal) if subtotal else 0
                    
                    row_html = (
                        f"<tr>"
                        f"<td style=\"text-align: left\">{product_name}</td>"
                        f"<td>{quantity}</td>"
                        f"<td>{_fmt_fr(unit_price)}</td>"
                        f"<td>{_fmt_fr(subtotal)}</td>"
                        f"</tr>"
                    )
                    # For BDL or legacy simple replacement
                    items_html += row_html + "\n"
                    # For Devis paginated tables
                    devis_rows.append(row_html)
                # Add filler rows to visually fill the table area to the footer
                try:
                    current_rows = len(self.sales_obj.items)
                    # Target rows per page tuned for current CSS; adjust if needed
                    target_rows = 22
                    filler_needed = max(0, target_rows - current_rows)
                    for _ in range(filler_needed):
                        items_html += """
                        <tr class=\"filler\">
                            <td style=\"text-align: left\">&nbsp;</td>
                            <td>&nbsp;</td>
                            <td>&nbsp;</td>
                            <td>&nbsp;</td>
                        </tr>
                        """
                except Exception:
                    pass
            else:
                print("DEBUG: No sales items found")
                items_html = '<tr><td colspan="4">No items found for this sale</td></tr>'
                devis_rows = []
                total_ht = 0
            
            # Calculate financial totals for devis
            total_remise = 0  # No discount system implemented yet
            total_regle = 0   # Amount already paid (could be from payments table if exists)
            net_a_payer = total_ht - total_remise - total_regle
            
            # Build paginated items for devis template if requested
            devis_items_html = ""
            if report_type in ('devis', 'facture'):
                # Row capacities (calibrated):
                # - single page (header+table+totals) => base-2
                # - first of multi (header+table)     => base+1
                # - middle pages (table only)         => base+10
                # - last page (table+totals)          => base-4
                BASE = 18
                rows_one_page = 21                # single page needs more rows
                rows_first_multi = 25             # first page of multi needs more rows
                rows_middle = 29                  # middle pages a bit more
                rows_last = 29                    # last page a lot more rows before totals

                total_rows = len(devis_rows)
                if total_rows == 0:
                    # Render a single empty table with one filler row so borders appear
                    pages = [(0, rows_one_page)]
                elif total_rows <= rows_one_page:
                    pages = [(total_rows, rows_one_page)]
                else:
                    remaining = total_rows
                    pages = []
                    # First page (no bottom yet)
                    take = min(remaining, rows_first_multi)
                    pages.append((take, rows_first_multi))
                    remaining -= take
                    # Middle pages
                    while remaining > rows_last:
                        take = min(remaining, rows_middle)
                        pages.append((take, rows_middle))
                        remaining -= take
                    # Last page
                    pages.append((remaining, rows_last))

                # Build HTML tables with page breaks
                cursor = 0
                for idx, (take, capacity) in enumerate(pages):
                    page_rows = devis_rows[cursor:cursor + take]
                    cursor += take
                    fillers = max(0, capacity - len(page_rows))
                    block_class = "items-block page-break" if idx < len(pages) - 1 else "items-block"
                    table_html = [f'<div class="{block_class}">']
                    table_html.append('<table>')
                    table_html.append('<thead><tr>'
                                      '<th>Désignation</th>'
                                      '<th>Qté</th>'
                                      '<th>P.U HT</th>'
                                      '<th>Total HT</th>'
                                      '</tr></thead>')
                    table_html.append('<tbody>')
                    table_html.extend(page_rows)
                    for _ in range(fillers):
                        table_html.append('<tr class="filler"><td style="text-align: left">&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td><td>&nbsp;</td></tr>')
                    table_html.append('</tbody></table></div>')
                    devis_items_html += "".join(table_html)

            # No separate BDL logic anymore
            total_qte_commandee = 0
            total_qte_livree = 0
            reste_a_livrer = 0

            return {
                'company_name': company_name,
                'company_phone': company_phone,
                'company_address': company_address,
                'company_email': company_email,
                'report_footer': report_footer.replace('\n', '<br/>'),
                'company_siret': "",  # Add if available in profile
                'company_tva': "",    # Add if available in profile
                'date': date,
                'document_ref': doc_ref,
                'client_name': client_name,
                'client_address': company_address,  # Use company address as fallback
                'commercial': "Sales Team",         # Default commercial
                'items': (devis_items_html if report_type in ('devis','facture') else items_html),
                # New financial fields for devis
                'total_remise': _fmt_fr(total_remise),
                'total_ht': _fmt_fr(total_ht),
                'total_regle': _fmt_fr(total_regle),
                'net_a_payer': _fmt_fr(net_a_payer),
                # BDL specific fields
                'total_commande': str(total_qte_commandee),
                'total_livre': str(total_qte_livree),
                'reste_a_livrer': str(reste_a_livrer),
                # Logo block
                'logo_block': logo_block
            }
        except Exception as e:
            print(f"Error extracting sales data: {e}")
            # Return default data structure
            return {
                'company_name': 'Your Company',
                'company_phone': '',
                'report_footer': '',
                'company_siret': '',
                'company_tva': '',
                'date': datetime.now().strftime("%d-%m-%Y"),
                'document_ref': 'DOC-000001',
                'client_name': 'Client Name',
                'client_address': '',
                'commercial': 'Sales Team',
                'items': '<tr><td colspan="4">No items found</td></tr>',
                # Financial fields for devis
                'total_remise': '0,00',
                'total_ht': '0,00',
                'total_regle': '0,00',
                'net_a_payer': '0,00',
                # BDL specific fields
                'total_commande': '0',
                'total_livre': '0',
                'reste_a_livrer': '0',
                'logo_block': '<div class="logo-placeholder">LOGO</div>'
            }
    
    def _replace_placeholders(self, template_content, data):
        """Replace template placeholders with actual data"""
        for key, value in data.items():
            placeholder = f"{{{{ {key} }}}}"
            template_content = template_content.replace(placeholder, str(value))
        
        return template_content
    
    def _html_to_pdf(self, html_content, output_path):
        """Convert HTML to PDF with full CSS support"""
        try:
            # Create a temporary HTML file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_html:
                temp_html.write(html_content)
                temp_html_path = temp_html.name
            
            # Try playwright first (best CSS support)
            try:
                from playwright.sync_api import sync_playwright
                print("DEBUG: Using Playwright for PDF generation")
                
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.set_content(html_content, wait_until='networkidle')
                    
                    # Configure PDF options for A4 size with proper margins and page breaks
                    pdf_options = {
                        'path': output_path,
                        'format': 'A4',
                        'margin': {
                            'top': '0.5in',
                            'bottom': '0.5in', 
                            'left': '0.5in',
                            'right': '0.5in'
                        },
                        'print_background': True,
                        'prefer_css_page_size': False,
                        'width': '8.27in',  # A4 width
                        'height': '11.69in'  # A4 height
                    }
                    
                    page.pdf(**pdf_options)
                    browser.close()
                    
                os.unlink(temp_html_path)
                print(f"DEBUG: Successfully generated PDF with Playwright: {output_path}")
                return output_path
            except ImportError:
                print("DEBUG: Playwright not available")
                pass
            except Exception as e:
                print(f"DEBUG: Playwright failed: {e}")
            
            # Try xhtml2pdf as fallback (limited CSS support)
            try:
                from xhtml2pdf import pisa
                print("DEBUG: Using xhtml2pdf for PDF generation")
                
                with open(output_path, "wb") as result_file:
                    # Convert HTML to PDF
                    pisa_status = pisa.CreatePDF(html_content, dest=result_file)
                    
                    if not pisa_status.err:
                        os.unlink(temp_html_path)
                        print(f"DEBUG: Successfully generated PDF with xhtml2pdf: {output_path}")
                        return output_path
                    else:
                        print(f"DEBUG: xhtml2pdf reported errors: {pisa_status.err}")
                        
            except ImportError:
                print("DEBUG: xhtml2pdf not available")
                pass
            except Exception as e:
                print(f"DEBUG: xhtml2pdf failed: {e}")
            
            # Try weasyprint third
            try:
                import weasyprint
                print("DEBUG: Using WeasyPrint for PDF generation")
                html = weasyprint.HTML(string=html_content)
                html.write_pdf(output_path)
                os.unlink(temp_html_path)
                print(f"DEBUG: Successfully generated PDF with WeasyPrint: {output_path}")
                return output_path
            except ImportError:
                print("DEBUG: WeasyPrint not available")
                pass
            except Exception as e:
                print(f"DEBUG: WeasyPrint failed: {e}")
            
            # Try pdfkit as last resort
            try:
                import pdfkit
                print("DEBUG: Using PDFKit for PDF generation")
                # Configure pdfkit options for better compatibility
                options = {
                    'page-size': 'A4',
                    'margin-top': '0.75in',
                    'margin-right': '0.75in',
                    'margin-bottom': '0.75in',
                    'margin-left': '0.75in',
                    'encoding': "UTF-8",
                    'no-outline': None
                }
                pdfkit.from_string(html_content, output_path, options=options)
                os.unlink(temp_html_path)
                print(f"DEBUG: Successfully generated PDF with PDFKit: {output_path}")
                return output_path
            except ImportError:
                print("DEBUG: PDFKit not available")
                pass
            except Exception as e:
                print(f"DEBUG: PDFKit failed: {e}")
            
            # If PDF generation fails, save as HTML with proper extension
            print("DEBUG: Falling back to HTML generation")
            html_output_path = output_path.replace('.pdf', '.html')
            with open(html_output_path, 'w', encoding='utf-8') as f:
                f.write(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Sales Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: white; color: black; }}
        .notice {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 10px; margin: 10px 0; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="notice">
        <strong>Note:</strong> PDF generation failed. This is an HTML version of your report. 
        For proper PDF generation, ensure weasyprint is properly installed.
    </div>
    {html_content}
</body>
</html>
                """)
            
            # Clean up temporary file
            os.unlink(temp_html_path)
            print(f"DEBUG: Generated HTML fallback: {html_output_path}")
            return html_output_path
            
        except Exception as e:
            # Clean up temporary file if it exists
            if 'temp_html_path' in locals() and os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                except:
                    pass
            print(f"DEBUG: HTML to PDF conversion failed: {e}")
            print(f"DEBUG: Output path: {output_path}")
            raise Exception(f"Failed to convert HTML to PDF: {str(e)}")
    

    
    def on_report_error(self, error_message):
        """Handle report generation error"""
        QApplication.restoreOverrideCursor()
        self.devis_btn.setEnabled(True)
        if hasattr(self, 'facture_btn'):
            self.facture_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", f"Failed to generate report:\n{error_message}")
    
    def open_pdf(self, pdf_path):
        """Open PDF/HTML file with default system application"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(pdf_path)
            elif os.name == 'posix':  # macOS and Linux
                subprocess.call(['open' if sys.platform == 'darwin' else 'xdg-open', pdf_path])
        except Exception as e:
            raise Exception(f"Could not open file: {str(e)}")