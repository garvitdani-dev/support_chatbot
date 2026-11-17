param(
    [Parameter(Mandatory=$true)]
    [string]$Tenant,
    [int]$Port = 8000,
    [switch]$ForceIndex
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project
$venvPython = Join-Path $project ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Virtual environment not found. Run .\setup_windows.ps1 first."
}
if (-not (Test-Path ".env")) {
    Write-Error ".env not found. Run .\setup_windows.ps1 first and configure it."
}

$indexArgs = @("-m", "app.cli", $Tenant)
if ($ForceIndex) { $indexArgs += "--force" }
& $venvPython @indexArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting http://127.0.0.1:$Port (Ctrl+C to stop)"
& $venvPython -m uvicorn app.api:app --host 127.0.0.1 --port $Port
