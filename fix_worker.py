import sys

with open('ui/dialogs/client_details_dialog.py', 'r', encoding='utf-8') as f:
    code = f.read()

import_replacement = """
import os
import tempfile
import html
import time
import base64
from pathlib import Path
from core.runtime_paths import resource_path
from ui.dialogs.reports_dialog import ReportsDialog
"""

worker_replacement = """
    def run(self):
        try:
            html_content = self._generate_html()
            
            output_dir = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Documents", "PyLocalInventory", "Reports")
            os.makedirs(output_dir, exist_ok=True)
            
            # Use timestamp
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
"""

if "import base64" not in code:
    code = code.replace("import html\nimport time\nfrom pathlib import Path\nfrom ui.dialogs.reports_dialog import ReportsDialog", import_replacement)

# Regex or string replacement for run method
import re
code = re.sub(r'    @Slot\(\)\n    def run\(self\):.*?(?=    def _fmt_money)', "    @Slot()\n" + worker_replacement, code, flags=re.DOTALL)

# Fix logo block
code = code.replace('ReportsDialog(None, None, None)._get_lamidap_logo_block()', 'self._get_lamidap_logo_block()')

with open('ui/dialogs/client_details_dialog.py', 'w', encoding='utf-8') as f:
    f.write(code)
