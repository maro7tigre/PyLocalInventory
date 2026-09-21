# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)
browser_root = Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])
if not browser_root.is_dir():
    raise SystemExit(f'Playwright browser directory is missing: {browser_root}')

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')

report_root = project_root / 'report'
report_asset_extensions = {
    '.html', '.htm', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg',
    '.ttf', '.otf', '.woff', '.woff2',
}
required_report_assets = (
    'bdl_templet.html',
    'client_statement_templet.html',
    'devis_templet.html',
    'facture_templet.html',
    'import_bl_templet.html',
    'Receipt_templat.html',
    'supplier_statement_templet.html',
    'lamidap_logo.png',  # Compatibility asset for LAMIDAP-branded deployments.
)
for relative_path in required_report_assets:
    source = report_root / relative_path
    if not source.is_file():
        raise SystemExit(f'Required report asset is missing: {source}')

report_datas = []
for source in sorted(report_root.rglob('*')):
    if source.is_file() and source.suffix.lower() in report_asset_extensions:
        destination = str(Path('report') / source.parent.relative_to(report_root))
        report_datas.append((str(source), destination))

company_logo = project_root / 'assets' / 'lamibois.png'
if not company_logo.is_file():
    raise SystemExit(f'Required company logo is missing: {company_logo}')

application_datas = [
    (str(project_root / 'logo.png'), '.'),
    (str(company_logo), 'assets'),
    (str(browser_root), 'playwright-browsers'),
] + report_datas

# Include tracked database initialization resources, but never user databases.
database_dir = project_root / 'database'
if database_dir.is_dir():
    for pattern in ('*.sql', '*.json'):
        for source in database_dir.rglob(pattern):
            destination = str(Path('database') / source.parent.relative_to(database_dir))
            application_datas.append((str(source), destination))

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=playwright_datas + application_datas,
    hiddenimports=playwright_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['weasyprint', 'xhtml2pdf', 'pdfkit'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PyLocalInventory',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'logo.png'),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='PyLocalInventory',
)
