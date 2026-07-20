[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ProjectRoot = $PSScriptRoot
$VenvPath = Join-Path $ProjectRoot '.venv'
$PythonPath = Join-Path $VenvPath 'Scripts\python.exe'
$SpecPath = Join-Path $ProjectRoot 'PyLocalInventory.spec'
$ExePath = Join-Path $ProjectRoot 'dist\PyLocalInventory\PyLocalInventory.exe'
$BrowserPath = Join-Path $ProjectRoot '.playwright-browsers'

try {
    Set-Location $ProjectRoot

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        Write-Host 'Creating .venv...'
        python -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) { throw 'Unable to create .venv. Install Python 3.10 or newer and ensure python is on PATH.' }
    }

    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    Write-Host 'Installing application and build dependencies...'
    & $PythonPath -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
    & $PythonPath -m pip install -r (Join-Path $ProjectRoot 'requirements.txt') 'PyInstaller==6.21.0'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserPath
    Write-Host 'Installing the pinned Chromium report engine...'
    & $PythonPath -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed.' }

    foreach ($DirectoryName in @('build', 'dist')) {
        $Target = Join-Path $ProjectRoot $DirectoryName
        if (Test-Path -LiteralPath $Target) {
            Write-Host "Removing old $DirectoryName output..."
            Remove-Item -LiteralPath $Target -Recurse -Force
        }
    }

    Write-Host 'Building PyLocalInventory (onedir)...'
    & $PythonPath -m PyInstaller --noconfirm --clean $SpecPath
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE." }

    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Build completed without the expected executable: $ExePath"
    }
    $BaseLibrary = Join-Path $ProjectRoot 'dist\PyLocalInventory\_internal\base_library.zip'
    if (-not (Test-Path -LiteralPath $BaseLibrary -PathType Leaf)) {
        throw "Build is incomplete: $BaseLibrary is missing; Python encodings cannot start without it."
    }
    foreach ($Resource in @(
        'dist\PyLocalInventory\_internal\report\devis_templet.html',
        'dist\PyLocalInventory\_internal\report\bdl_templet.html',
        'dist\PyLocalInventory\_internal\report\facture_templet.html',
        'dist\PyLocalInventory\_internal\report\Receipt_templat.html',
        'dist\PyLocalInventory\_internal\report\lamidap_logo.png',
        'dist\PyLocalInventory\_internal\playwright-browsers'
    )) {
        $ResolvedResource = Join-Path $ProjectRoot $Resource
        if (-not (Test-Path -LiteralPath $ResolvedResource)) {
            throw "Build is incomplete: required resource is missing: $ResolvedResource"
        }
    }

    Write-Host "Build succeeded: $ExePath" -ForegroundColor Green
    Write-Host 'Keep the EXE and its _internal folder together when deploying.'
}
catch {
    Write-Error "Windows build failed: $($_.Exception.Message)"
    exit 1
}
