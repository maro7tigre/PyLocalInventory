[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ProfileName,
    [ValidateRange(1, 65535)][int]$Port = 8765,
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
$python = Join-Path $repo ".venv\Scripts\python.exe"
$serviceScript = Join-Path $repo "core\network\windows_service.py"
$serviceName = "PyLocalInventoryLAN"
$serviceRoot = Join-Path $env:ProgramData "PyLocalInventory\LANService"
$dataRoot = Join-Path $serviceRoot "data"
$runtimeRoot = Join-Path $serviceRoot "runtime"
$legacyAttachments = Join-Path $env:LOCALAPPDATA "PyLocalInventory\attachments"
$sc = Join-Path $env:SystemRoot "System32\sc.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual environment Python is missing: $python"
}

& $python -c "import win32serviceutil, win32crypt" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "pywin32 is missing. Run: .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# Retire the previous per-user detached host before the SCM service owns the
# port. This requests a graceful stop and removes only its obsolete Run entry.
& $python -c "from core.network.host_process import HostProcessController; HostProcessController.stop()" 2>$null
Start-Sleep -Seconds 2
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
    -Name 'PyLocalInventory LAN Host' -ErrorAction SilentlyContinue

# Restrict the machine-wide root before writing the DPAPI-protected database
# configuration. This avoids even a brief inherited read window for users.
New-Item -ItemType Directory -Path $serviceRoot -Force | Out-Null
& icacls.exe $serviceRoot /inheritance:r /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(X)' /T /C | Out-Null

& $python $serviceScript configure --profile $ProfileName --port $Port
if ($LASTEXITCODE -ne 0) { throw "Service configuration failed." }

New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (Test-Path -LiteralPath $legacyAttachments -PathType Container) {
    $destination = Join-Path $dataRoot "attachments"
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Get-ChildItem -LiteralPath $legacyAttachments -Force | Copy-Item -Destination $destination -Recurse -Force -ErrorAction Stop
}

# LocalSystem runs the service. Interactive desktop users need shared
# attachment access and read-only status access, but never PostgreSQL secrets.
& icacls.exe $repo /grant '*S-1-5-18:(OI)(CI)RX' /T /C | Out-Null
& icacls.exe $runtimeRoot /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)RX' /T /C | Out-Null
& icacls.exe $dataRoot /grant:r `
    '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-32-545:(OI)(CI)M' /T /C | Out-Null

$existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    & $python $serviceScript --startup auto install
} else {
    if ($existing.Status -ne 'Stopped') {
        Stop-Service -Name $serviceName -Force
        $existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    }
    & $python $serviceScript --startup auto update
}
if ($LASTEXITCODE -ne 0) { throw "Windows Service installation/update failed." }

& $sc config $serviceName start= auto | Out-Null
& $sc failure $serviceName reset= 86400 actions= restart/5000/restart/15000/restart/30000 | Out-Null
& $sc failureflag $serviceName 1 | Out-Null

if (-not $NoStart) {
    Start-Service -Name $serviceName
    (Get-Service -Name $serviceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
}

Write-Host "PyLocalInventory LAN Service installed." -ForegroundColor Green
Write-Host "Profile: $ProfileName  Port: $Port"
Write-Host "Configuration: $serviceRoot"
