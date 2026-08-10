[CmdletBinding()]
param(
    [switch]$RunAfterBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$VenvPath = Join-Path $RepositoryRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$RequirementsPath = Join-Path $RepositoryRoot "requirements.txt"
$SpecPath = Join-Path $RepositoryRoot "PyLocalInventory.spec"
$BuildPath = Join-Path $RepositoryRoot "build"
$DistPath = Join-Path $RepositoryRoot "dist"
$ApplicationFolder = Join-Path $DistPath "PyLocalInventory"
$ExePath = Join-Path $ApplicationFolder "PyLocalInventory.exe"
$InternalPath = Join-Path $ApplicationFolder "_internal"
$BrowserCachePath = Join-Path $RepositoryRoot ".playwright-browsers"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Get-SystemPython {
    $PyLauncher = Get-Command "py" -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        return @($PyLauncher.Source, "-3")
    }

    $PythonCommand = Get-Command "python" -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $PythonCommand) {
        return @($PythonCommand.Source)
    }

    throw "Python was not found. Install Python 3.10 or newer and enable either the 'py' launcher or 'python' command."
}

try {
    Set-Location -LiteralPath $RepositoryRoot
    Write-Host "Repository root: $RepositoryRoot"

    foreach ($RequiredSource in @("main.py", "requirements.txt", "PyLocalInventory.spec", "logo.png", "report")) {
        $RequiredPath = Join-Path $RepositoryRoot $RequiredSource
        if (-not (Test-Path -LiteralPath $RequiredPath)) {
            throw "Required project source is missing: $RequiredPath"
        }
    }

    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        $PythonCommand = @(Get-SystemPython)
        $SystemPython = $PythonCommand[0]
        $LauncherArguments = @()
        if ($PythonCommand.Count -gt 1) {
            $LauncherArguments += $PythonCommand[1..($PythonCommand.Count - 1)]
        }
        $LauncherArguments += @("-m", "venv", $VenvPath)
        Write-Host "Creating virtual environment with $SystemPython..."
        Invoke-Checked -FilePath $SystemPython -Arguments $LauncherArguments -FailureMessage "Virtual environment creation failed"
    }

    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        throw "Virtual environment creation completed without producing: $VenvPython"
    }

    Write-Host "Upgrading pip, setuptools, wheel, PyInstaller, and Pillow..."
    Invoke-Checked -FilePath $VenvPython -Arguments @(
        "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "pyinstaller", "pillow"
    ) -FailureMessage "Build-tool installation failed"

    Write-Host "Installing application requirements..."
    Invoke-Checked -FilePath $VenvPython -Arguments @(
        "-m", "pip", "install", "--upgrade", "-r", $RequirementsPath
    ) -FailureMessage "Application dependency installation failed"

    if (Test-Path -LiteralPath $BrowserCachePath) {
        Write-Host "Removing stale generated browser cache: $BrowserCachePath"
        Remove-Item -LiteralPath $BrowserCachePath -Recurse -Force
    }
    $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserCachePath
    Write-Host "Installing the Chromium headless PDF engine..."
    Invoke-Checked -FilePath $VenvPython -Arguments @(
        "-m", "playwright", "install", "--only-shell", "chromium"
    ) -FailureMessage "Chromium installation failed"

    foreach ($GeneratedPath in @($BuildPath, $DistPath)) {
        if (Test-Path -LiteralPath $GeneratedPath) {
            Write-Host "Removing old generated directory: $GeneratedPath"
            Remove-Item -LiteralPath $GeneratedPath -Recurse -Force
        }
        New-Item -ItemType Directory -Path $GeneratedPath -Force | Out-Null
    }

    Write-Host "Building PyLocalInventory in onedir mode from $SpecPath..."
    Invoke-Checked -FilePath $VenvPython -Arguments @(
        "-m", "PyInstaller", "--noconfirm", "--clean",
        "--workpath", $BuildPath, "--distpath", $DistPath, $SpecPath
    ) -FailureMessage "PyInstaller build failed"

    $DistItems = @(Get-ChildItem -LiteralPath $DistPath -Force)
    if ($DistItems.Count -eq 0) {
        throw "PyInstaller reported success but the dist directory is empty: $DistPath"
    }
    if (-not (Test-Path -LiteralPath $ApplicationFolder -PathType Container)) {
        throw "Final application folder is missing: $ApplicationFolder"
    }
    if (-not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
        throw "Final executable is missing: $ExePath"
    }
    if ((Get-Item -LiteralPath $ExePath).Length -le 0) {
        throw "Final executable is zero bytes: $ExePath"
    }
    if (-not (Test-Path -LiteralPath $InternalPath -PathType Container)) {
        throw "The required PyInstaller _internal directory is missing: $InternalPath"
    }

    foreach ($RuntimeFile in @("base_library.zip", "logo.png")) {
        $RuntimePath = Join-Path $InternalPath $RuntimeFile
        if (-not (Test-Path -LiteralPath $RuntimePath -PathType Leaf)) {
            throw "Required runtime file is missing: $RuntimePath"
        }
    }

    $SourceReportPath = Join-Path $RepositoryRoot "report"
    $PackagedReportPath = Join-Path $InternalPath "report"
    $SourceReportAssets = @(Get-ChildItem -LiteralPath $SourceReportPath -File -Recurse)
    foreach ($SourceAsset in $SourceReportAssets) {
        $RelativeAsset = $SourceAsset.FullName.Substring($SourceReportPath.Length).TrimStart([char[]]"\/")
        $PackagedAsset = Join-Path $PackagedReportPath $RelativeAsset
        if (-not (Test-Path -LiteralPath $PackagedAsset -PathType Leaf)) {
            throw "Required report asset is missing from the build: $PackagedAsset"
        }
    }

    # The canonical LAMIBOIS logo must be bundled byte-for-byte identical.
    $SourceLogoPath = Join-Path $RepositoryRoot "assets\lamibois.png"
    $PackagedLogoPath = Join-Path $InternalPath "assets\lamibois.png"
    if (-not (Test-Path -LiteralPath $PackagedLogoPath -PathType Leaf)) {
        throw "The new LAMIBOIS logo is missing from the build: $PackagedLogoPath"
    }
    $SourceLogoHash = (Get-FileHash -LiteralPath $SourceLogoPath -Algorithm SHA256).Hash
    $PackagedLogoHash = (Get-FileHash -LiteralPath $PackagedLogoPath -Algorithm SHA256).Hash
    if ($SourceLogoHash -ne $PackagedLogoHash) {
        throw "The packaged logo does not match the canonical assets\lamibois.png"
    }

    $PackagedBrowser = Get-ChildItem -LiteralPath (Join-Path $InternalPath "playwright-browsers") `
        -Filter "chrome-headless-shell.exe" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $PackagedBrowser) {
        throw "The bundled Chromium PDF executable is missing under $InternalPath\playwright-browsers."
    }

    $FolderBytes = (Get-ChildItem -LiteralPath $ApplicationFolder -File -Recurse | Measure-Object -Property Length -Sum).Sum
    $FolderSizeMB = [Math]::Round($FolderBytes / 1MB, 2)

    Write-Host ""
    Write-Host "Build succeeded." -ForegroundColor Green
    Write-Host "EXE path: $ExePath" -ForegroundColor Green
    Write-Host "Application folder: $ApplicationFolder" -ForegroundColor Green
    Write-Host "Application folder size: $FolderSizeMB MB" -ForegroundColor Green

    if ($RunAfterBuild) {
        Write-Host "Launching $ExePath..."
        Start-Process -FilePath $ExePath -WorkingDirectory $ApplicationFolder
    }
}
catch {
    Write-Error "Windows build failed: $($_.Exception.Message)"
    exit 1
}
