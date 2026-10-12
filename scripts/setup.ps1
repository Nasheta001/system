# One-time local setup for Windows PowerShell.
# Run from the project root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Options:  -NoDemo   (skip loading fictional demo data)
param([switch]$NoDemo)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "== Backend ==" -ForegroundColor Cyan
Set-Location $backend
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\pip.exe install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    $key = & .\.venv\Scripts\python.exe -c "import secrets;print(secrets.token_urlsafe(50))"
    $cb = & .\.venv\Scripts\python.exe -c "import secrets;print(secrets.token_urlsafe(24))"
    $fk = & .\.venv\Scripts\python.exe -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    (Get-Content ".env") `
        -replace "^DJANGO_SECRET_KEY=.*", "DJANGO_SECRET_KEY=$key" `
        -replace "^MPESA_CALLBACK_TOKEN=.*", "MPESA_CALLBACK_TOKEN=$cb" `
        -replace "^FIELD_ENCRYPTION_KEYS=.*", "FIELD_ENCRYPTION_KEYS=$fk" `
        -replace "^DATABASE_URL=.*", "# DATABASE_URL=postgres://propman:PASSWORD@localhost:5432/propman  (run scripts\setup-postgres.ps1)" `
        -replace "^EMAIL_BACKEND=.*", "EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend" |
        Set-Content ".env" -Encoding utf8
    Write-Host "Created backend\.env with fresh secrets (SQLite until PostgreSQL is configured)."
}

& .\.venv\Scripts\python.exe manage.py migrate
if ($LASTEXITCODE -ne 0) { throw "migrate failed" }
& .\.venv\Scripts\python.exe manage.py setup_defaults
if (-not $NoDemo) {
    & .\.venv\Scripts\python.exe manage.py seed_demo
    if ($LASTEXITCODE -ne 0) { Write-Host "Demo data not loaded (database already has properties). Use: python manage.py seed_demo --reset" -ForegroundColor Yellow }
}

Write-Host "== Frontend ==" -ForegroundColor Cyan
Set-Location $frontend
npm install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

Set-Location $root
Write-Host ""
Write-Host "Setup complete. Start the app with:" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1"
Write-Host "Then open http://localhost:4200"
