# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)
browser_root = Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])
if not browser_root.is_dir():
    raise SystemExit(f'Playwright browser directory is missing: {browser_root}')

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all('playwright')

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root)],
    binaries=playwright_binaries,
    datas=playwright_datas + [
        (str(project_root / 'logo.png'), '.'),
        (str(project_root / 'report'), 'report'),
        (str(browser_root), 'playwright-browsers'),
    ],
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
