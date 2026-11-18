[CmdletBinding()]
param(
    [string]$PythonExecutable
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from PowerShell as Administrator."
}

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $PythonExecutable = @(
        (Join-Path $repo ".venv\Scripts\python.exe"),
        ($repo + ".venv\Scripts\python.exe")
    ) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}
if ([string]::IsNullOrWhiteSpace($PythonExecutable) -or
        -not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Pass -PythonExecutable with the full path to the service virtual environment Python."
}
$python = (Resolve-Path -LiteralPath $PythonExecutable).Path
$serviceScript = Join-Path $repo "core\network\windows_service.py"
$serviceName = "PyLocalInventoryLAN"
$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

if ($null -ne $service) {
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $serviceName -Force
        $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    }
    & $python $serviceScript remove
    if ($LASTEXITCODE -ne 0) { throw "Windows Service removal failed." }
}

Write-Host "PyLocalInventory LAN Service removed." -ForegroundColor Green
Write-Host "ProgramData configuration, logs, and attachments were preserved intentionally."
