param(
    [string]$Python = "py",
    [string]$Venv = ".venv"
)

$ErrorActionPreference = "Stop"
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $project

if ($Python -eq "py") {
    & $Python -3 -m venv $Venv
} else {
    & $Python -m venv $Venv
}
if ($LASTEXITCODE -ne 0) {
    Write-Error "Python 3 was not found. Install Python 3.11+ and enable the Python launcher, then rerun this script."
}

$venvPython = Join-Path $project "$Venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Add your OpenAI settings and bearer token before starting."
}

Write-Host "Windows setup complete. Start with: .\run_windows.ps1 -Tenant spring-garden"
