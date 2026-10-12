# Turns on real email delivery (invitations, password resets, receipts) for the local backend.
# Default: Gmail SMTP with an App Password (https://myaccount.google.com/apppasswords - needs 2-Step Verification).
# The password is typed here and written only to backend\.env (git-ignored); it is never printed.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\configure-email.ps1
param(
    [string]$SmtpHost = "smtp.gmail.com",
    [int]$Port = 587
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "backend\.env"

$user = Read-Host "Sender email address (e.g. yourname@gmail.com)"
$secure = Read-Host "App password for $user (input hidden)" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
$plain = $plain -replace "\s", ""   # Gmail shows app passwords in groups of four
if (-not $user -or -not $plain) { throw "Email and password are required." }

$values = [ordered]@{
    NOTIFY_EMAIL_ENABLED = "true"
    EMAIL_BACKEND        = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST           = $SmtpHost
    EMAIL_PORT           = "$Port"
    EMAIL_USE_TLS        = "true"
    EMAIL_HOST_USER      = $user
    EMAIL_HOST_PASSWORD  = $plain
    DEFAULT_FROM_EMAIL   = $user
}
$lines = if (Test-Path $envFile) { Get-Content $envFile } else { @() }
foreach ($k in $values.Keys) {
    $found = $false
    $lines = $lines | ForEach-Object { if ($_ -match "^$k=") { $found = $true; "$k=$($values[$k])" } else { $_ } }
    if (-not $found) { $lines += "$k=$($values[$k])" }
}
[IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))   # no BOM
Write-Host "Saved email settings to backend\.env (password not shown)." -ForegroundColor Green

Write-Host "Sending a test email to $user ..." -ForegroundColor Cyan
Push-Location (Join-Path $root "backend")
& .\.venv\Scripts\python.exe manage.py sendtestemail $user
$ok = $LASTEXITCODE -eq 0
Pop-Location
if ($ok) {
    Write-Host "Test email sent. Restart the backend (scripts\start-backend.ps1), then click 'Resend portal invitation'." -ForegroundColor Green
} else {
    Write-Host "Sending failed. Check the address and app password (normal Gmail passwords do not work)." -ForegroundColor Red
}
