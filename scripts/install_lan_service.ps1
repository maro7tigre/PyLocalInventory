[CmdletBinding()]
param(
    [string]$ProfileName,
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [string]$PythonExecutable,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from PowerShell as Administrator."
}

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$serviceScript = Join-Path $repo "core\network\windows_service.py"
$serviceName = "PyLocalInventoryLAN"
$serviceRoot = Join-Path $env:ProgramData "PyLocalInventory\LANService"
$serviceConfig = Join-Path $serviceRoot "service.json"
$dataRoot = Join-Path $serviceRoot "data"
$runtimeRoot = Join-Path $serviceRoot "runtime"
$logsRoot = Join-Path $serviceRoot "logs"
$legacyAttachments = Join-Path $env:LOCALAPPDATA "PyLocalInventory\attachments"
$sc = Join-Path $env:SystemRoot "System32\sc.exe"

if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $pythonCandidates = @(
        (Join-Path $repo ".venv\Scripts\python.exe"),
        ($repo + ".venv\Scripts\python.exe")
    )
    $PythonExecutable = $pythonCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($PythonExecutable) -or
        -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Virtual environment Python was not found. Pass -PythonExecutable with the full path to .venv\Scripts\python.exe."
}
$python = (Resolve-Path -LiteralPath $PythonExecutable).Path

& $python -c "import win32serviceutil, win32crypt, servicemanager" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "pywin32 is missing from $python. Install requirements with that interpreter."
}

# Ask the selected interpreter for authoritative paths. A venv launcher does
# not contain python3XX.dll; that DLL normally lives in its base installation.
$runtimeJson = & $python -c @'
import json, pathlib, sys
import pythoncom, pywintypes, win32api, win32service
service_source = pathlib.Path(win32service.__file__).with_name("pythonservice.exe")
service_target = pathlib.Path(sys.prefix) / "pythonservice.exe"
print(json.dumps({
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "python_dll": win32api.GetModuleFileName(sys.dllhandle),
    "pywintypes_dll": pywintypes.__file__,
    "pythoncom_dll": pythoncom.__file__,
    "service_source": str(service_source),
    "service_target": str(service_target),
    "version_tag": f"{sys.version_info.major}{sys.version_info.minor}",
}))
'@
if ($LASTEXITCODE -ne 0) { throw "Could not inspect the selected Python runtime." }
$runtime = $runtimeJson | ConvertFrom-Json
$venvRoot = [IO.Path]::GetFullPath([string]$runtime.prefix)
$basePythonRoot = [IO.Path]::GetFullPath([string]$runtime.base_prefix)
$serviceHost = [IO.Path]::GetFullPath([string]$runtime.service_target)

if (-not (Test-Path -LiteralPath (Join-Path $venvRoot "pyvenv.cfg") -PathType Leaf)) {
    throw "$python is not a usable virtual environment (pyvenv.cfg is missing from $venvRoot)."
}
if (-not (Test-Path -LiteralPath $runtime.python_dll -PathType Leaf)) {
    throw "Python runtime DLL is missing: $($runtime.python_dll)"
}

# Stop the existing service before replacing loader files. This is a repair or
# update only; ProgramData configuration and business data are retained.
$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($null -ne $existing -and $existing.Status -ne 'Stopped') {
    Stop-Service -Name $serviceName -Force
    $existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
}

function Copy-RuntimeFile([string]$Source, [string]$Destination) {
    $sourcePath = [IO.Path]::GetFullPath($Source)
    $destinationPath = [IO.Path]::GetFullPath($Destination)
    if (-not [string]::Equals($sourcePath, $destinationPath, [StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    }
}

# Windows resolves imported DLLs beside pythonservice.exe before Python gets a
# chance to process pyvenv.cfg. Co-locating these files removes any dependence
# on HP1's interactive PATH during a LocalSystem boot start.
$serviceSource = [string]$runtime.service_source
if (Test-Path -LiteralPath $serviceSource -PathType Leaf) {
    Copy-RuntimeFile $serviceSource $serviceHost
} elseif (-not (Test-Path -LiteralPath $serviceHost -PathType Leaf)) {
    throw "pythonservice.exe is missing from both $serviceSource and $serviceHost"
}
Copy-RuntimeFile ([string]$runtime.python_dll) `
    (Join-Path $venvRoot ([IO.Path]::GetFileName([string]$runtime.python_dll)))
Copy-RuntimeFile ([string]$runtime.pywintypes_dll) `
    (Join-Path $venvRoot ([IO.Path]::GetFileName([string]$runtime.pywintypes_dll)))
Copy-RuntimeFile ([string]$runtime.pythoncom_dll) `
    (Join-Path $venvRoot ([IO.Path]::GetFileName([string]$runtime.pythoncom_dll)))

# Retire the previous per-user detached host before SCM owns the port.
& $python -c "from core.network.host_process import HostProcessController; HostProcessController.stop()" 2>$null
Start-Sleep -Seconds 2
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
    -Name 'PyLocalInventory LAN Host' -ErrorAction SilentlyContinue

# Restrict the machine-wide root before writing any DPAPI-protected settings.
New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
& icacls.exe $serviceRoot /inheritance:r /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(X)' /T /C | Out-Null

if (-not [string]::IsNullOrWhiteSpace($ProfileName)) {
    & $python $serviceScript configure --profile $ProfileName --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Service configuration failed." }
} elseif (Test-Path -LiteralPath $serviceConfig -PathType Leaf) {
    & $python $serviceScript repair-runtime `
        --python-executable $python --project-root $repo
    if ($LASTEXITCODE -ne 0) { throw "Updating service runtime paths failed." }
} else {
    throw "-ProfileName is required for the first installation. Repair mode requires an existing $serviceConfig."
}

New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $logsRoot -Force | Out-Null
if ((Test-Path -LiteralPath $legacyAttachments -PathType Container) -and
        -not (Test-Path -LiteralPath (Join-Path $dataRoot "attachments"))) {
    Copy-Item -LiteralPath $legacyAttachments -Destination $dataRoot -Recurse -ErrorAction Stop
}

# LocalSystem needs read/execute access to source, venv, and the base standard
# library referenced by pyvenv.cfg. No write access is granted.
$systemReadRoots = @($repo, $venvRoot, $basePythonRoot) | Select-Object -Unique
foreach ($path in $systemReadRoots) {
    & icacls.exe $path /grant '*S-1-5-18:(OI)(CI)RX' /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not grant LocalSystem read access to $path" }
}
& icacls.exe $runtimeRoot /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /T /C | Out-Null
& icacls.exe $dataRoot /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)M' /T /C | Out-Null

if ($null -eq $existing) {
    & $python $serviceScript --startup auto install
} else {
    & $python $serviceScript --startup auto update
}
if ($LASTEXITCODE -ne 0) { throw "Windows Service installation/update failed." }

# Make both pywin32-specific and SCM registration explicit. This prevents an
# old venv path or an import name based on the caller's working directory from
# surviving an update.
$serviceModule = Join-Path ([IO.Path]::GetDirectoryName($serviceScript)) `
    ([IO.Path]::GetFileNameWithoutExtension($serviceScript))
$pythonClass = $serviceModule + ".PyLocalInventoryLANService"
$pythonClassKey = "HKLM:\SYSTEM\CurrentControlSet\Services\$serviceName\PythonClass"
New-Item -Path $pythonClassKey -Force | Out-Null
Set-Item -Path $pythonClassKey -Value $pythonClass

$quotedServiceHost = '"' + $serviceHost + '"'
& $sc config $serviceName binPath= $quotedServiceHost start= auto obj= LocalSystem | Out-Null
if ($LASTEXITCODE -ne 0) { throw "SCM rejected the pythonservice.exe path." }
& $sc failure $serviceName reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null
& $sc failureflag $serviceName 1 | Out-Null

# Fail before SCM start if the native loader dependencies are not beside the
# service host. These checks directly cover the common 7000/7009 cause.
$requiredLoaderFiles = @(
    $serviceHost,
    (Join-Path $venvRoot ("python" + $runtime.version_tag + ".dll")),
    (Join-Path $venvRoot ("pywintypes" + $runtime.version_tag + ".dll"))
)
foreach ($path in $requiredLoaderFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required service loader file is missing: $path"
    }
}
$registeredClass = (Get-Item -LiteralPath $pythonClassKey).GetValue("")
$registeredService = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
if ($registeredClass -ne $pythonClass) {
    throw "PythonClass registration mismatch. Expected '$pythonClass', found '$registeredClass'."
}
if ($registeredService.PathName.Trim('"') -ne $serviceHost) {
    throw "SCM executable mismatch. Expected '$serviceHost', found '$($registeredService.PathName)'."
}
if ($registeredService.StartName -notin 'LocalSystem', 'NT AUTHORITY\SYSTEM') {
    throw "SCM account mismatch. Expected LocalSystem, found '$($registeredService.StartName)'."
}

if (-not $NoStart) {
    try {
        Start-Service -Name $serviceName
        (Get-Service -Name $serviceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(45))
        Start-Sleep -Seconds 3
        $started = Get-Service -Name $serviceName
        if ($started.Status -ne 'Running') {
            throw "The service entered Running state and then stopped."
        }
    } catch {
        $registeredService = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
        $diagnosticPath = Join-Path $logsRoot "install-startup-error.txt"
        $startTime = (Get-Date).AddMinutes(-10)
        $systemEvents = Get-WinEvent -FilterHashtable @{
            LogName = 'System'; ProviderName = 'Service Control Manager'; StartTime = $startTime
        } -ErrorAction SilentlyContinue | Where-Object {
            $_.Id -in 7000, 7001, 7009, 7011, 7023, 7024, 7031, 7034
        } | Select-Object -First 12 TimeCreated, Id, LevelDisplayName, Message
        $applicationEvents = Get-WinEvent -FilterHashtable @{
            LogName = 'Application'; StartTime = $startTime
        } -ErrorAction SilentlyContinue | Where-Object {
            $_.ProviderName -match 'Python|PyLocalInventory'
        } | Select-Object -First 12 TimeCreated, Id, ProviderName, Message
        $diagnostic = @(
            "Startup error: $($_.Exception.Message)",
            "Service executable: $serviceHost",
            "PythonClass: $registeredClass",
            "Virtual environment: $venvRoot",
            "Base Python: $basePythonRoot",
            "Python DLL: $($runtime.python_dll)",
            "SCM state:",
            ($registeredService | Format-List Name, State, StartMode, StartName, PathName | Out-String),
            "Recent SCM events:",
            ($systemEvents | Format-List | Out-String),
            "Recent Python/Application events:",
            ($applicationEvents | Format-List | Out-String)
        ) -join [Environment]::NewLine
        [IO.File]::WriteAllText($diagnosticPath, $diagnostic)
        throw "LAN service did not start. Diagnostics: $diagnosticPath`n$diagnostic"
    }
}

Write-Host "PyLocalInventory LAN Service installed and runtime registration verified." -ForegroundColor Green
Write-Host "SCM executable: $serviceHost"
Write-Host "PythonClass: $pythonClass"
Write-Host "Configuration preserved at: $serviceRoot"
