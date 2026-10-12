# Security checks to run before every release (and in CI):
#   - Python dependency vulnerabilities (pip-audit)
#   - npm dependency vulnerabilities (npm audit)
#   - Django deployment checklist with production-like settings
#   - a scan of the working tree for committed secrets
# Usage: powershell -ExecutionPolicy Bypass -File scripts\security-scan.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
$failed = $false

Write-Host "== pip-audit" -ForegroundColor Cyan
& $py -m pip install --quiet -r (Join-Path $root "backend\requirements-dev.txt")
& $py -m pip_audit -r (Join-Path $root "backend\requirements.txt") --progress-spinner off
if ($LASTEXITCODE -ne 0) { $failed = $true }

Write-Host "== npm audit" -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend"); npm audit --audit-level=moderate; if ($LASTEXITCODE -ne 0) { $failed = $true }; Pop-Location

Write-Host "== Django check --deploy (production-like settings, no real secrets)" -ForegroundColor Cyan
$env:DJANGO_DEBUG = "false"; $env:SECURE_HTTPS = "true"; $env:DJANGO_ALLOWED_HOSTS = "www.example.co.ke"
$env:DJANGO_SECRET_KEY = & $py -c "import secrets;print(secrets.token_urlsafe(60))"
$env:FIELD_ENCRYPTION_KEYS = & $py -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
$env:DATABASE_URL = "sqlite:///" + (Join-Path $env:TEMP "deploycheck.sqlite3").Replace("\", "/")
Push-Location (Join-Path $root "backend")
$out = & $py manage.py check --deploy 2>&1 | Out-String
Pop-Location
foreach ($v in "DJANGO_DEBUG", "SECURE_HTTPS", "DJANGO_ALLOWED_HOSTS", "DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEYS", "DATABASE_URL") { Remove-Item "Env:\$v" -ErrorAction SilentlyContinue }
# W021 (HSTS preload) is an intentional opt-in: preloading a domain is hard to undo.
$securityWarnings = ($out -split "`n") | Where-Object { $_ -match "security\.W|security\.E" -and $_ -notmatch "security\.W021" }
if ($out -match "security\.W021") { Write-Host "Info: HSTS preload not enabled (set SECURE_HSTS_PRELOAD=true once the domain is ready)." }
if ($securityWarnings) { $securityWarnings; $failed = $true } else { Write-Host "No Django security warnings." }

Write-Host "== Secret scan (tracked source only)" -ForegroundColor Cyan
$patterns = @(
    "AKIA[0-9A-Z]{16}",                                   # AWS access key id
    "-----BEGIN (RSA |EC )?PRIVATE KEY-----",
    "(?i)(secret|password|passkey|api_key|token)\s*[:=]\s*['""][A-Za-z0-9_\-/+=]{16,}['""]"
)
$files = Get-ChildItem $root -Recurse -File -Include *.py, *.ts, *.json, *.yml, *.yaml, *.ps1, *.md, *.conf, *.html |
    Where-Object { $_.FullName -notmatch "\\(node_modules|\.venv|dist|\.angular|staticfiles)\\" }
$hits = $files | Select-String -Pattern $patterns
if ($hits) { $hits | ForEach-Object { "{0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim() }; $failed = $true } else { Write-Host "No secrets found in source files." }
if (Test-Path (Join-Path $root ".git")) {
    $tracked = git -C $root ls-files | Select-String -Pattern "(^|/)\.env$|docker\.env$|\.pem$|\.key$"
    if ($tracked) { Write-Host "Secret files are tracked by git:" -ForegroundColor Red; $tracked; $failed = $true }
}

if ($failed) { Write-Host "Security scan found issues." -ForegroundColor Red; exit 1 }
Write-Host "Security scan passed." -ForegroundColor Green
