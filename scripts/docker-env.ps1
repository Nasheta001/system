# Creates deploy\docker.env from the example with freshly generated secrets.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\docker-env.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "deploy\docker.env"
if (Test-Path $target) { Write-Host "deploy\docker.env already exists - not overwritten."; exit 0 }
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }
$dbPw = & $py -c "import secrets;print(secrets.token_hex(24))"
$secret = & $py -c "import secrets;print(secrets.token_urlsafe(50))"
$fieldKey = & $py -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
$cbToken = & $py -c "import secrets;print(secrets.token_urlsafe(32))"
$text = Get-Content (Join-Path $root "deploy\docker.env.example") -Raw
$text = $text -replace "POSTGRES_PASSWORD=CHANGE_ME", "POSTGRES_PASSWORD=$dbPw"
$text = $text -replace "propman:CHANGE_ME@", "propman:$dbPw@"
$text = $text -replace "DJANGO_SECRET_KEY=CHANGE_ME", "DJANGO_SECRET_KEY=$secret"
$text = $text -replace "FIELD_ENCRYPTION_KEYS=CHANGE_ME", "FIELD_ENCRYPTION_KEYS=$fieldKey"
$text = $text -replace "MPESA_CALLBACK_TOKEN=CHANGE_ME", "MPESA_CALLBACK_TOKEN=$cbToken"
[IO.File]::WriteAllText($target, $text)
# docker compose reads POSTGRES_PASSWORD for variable substitution from a root .env file
[IO.File]::WriteAllText((Join-Path $root ".env"), "POSTGRES_PASSWORD=$dbPw`n")
Write-Host "Created deploy\docker.env and .env (both git-ignored). Run: docker compose up --build" -ForegroundColor Green
