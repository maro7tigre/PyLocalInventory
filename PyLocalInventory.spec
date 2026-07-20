# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)
browser_root = Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])
if not browser_root.is_dir():
    raise SystemExit(f'Playwright browser directory is missing: {browser_root}')

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')

application_datas = [
    (str(project_root / 'logo.png'), '.'),
    (str(project_root / 'report'), 'report'),
    (str(browser_root), 'playwright-browsers'),
]

# Automatically include future runtime-only asset directories when present.
for resource_dir in ('assets', 'static', 'fonts', 'images', 'icons', 'translations', 'config'):
    source = project_root / resource_dir
    if source.is_dir():
        application_datas.append((str(source), resource_dir))

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
