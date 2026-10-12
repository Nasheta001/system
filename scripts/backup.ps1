# Backs up the PostgreSQL database and uploaded files into backups\<timestamp>\.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
# Reads DATABASE_URL from backend\.env. Schedule with Windows Task Scheduler (daily).
param([string]$PgBin = "C:\Program Files\PostgreSQL\17\bin", [int]$KeepDays = 30)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root "backend\.env"
$line = Get-Content $envFile | Where-Object { $_ -match "^DATABASE_URL=" } | Select-Object -First 1
if (-not $line) { throw "DATABASE_URL is not set in backend\.env (SQLite installs: copy backend\db.sqlite3 instead)." }
$uri = [Uri]($line -replace "^DATABASE_URL=", "")
$user, $pass = $uri.UserInfo.Split(":", 2)
$db = $uri.AbsolutePath.TrimStart("/")
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dest = Join-Path $root "backups\$stamp"
New-Item -ItemType Directory -Force $dest | Out-Null

$env:PGPASSWORD = [Uri]::UnescapeDataString($pass)
& (Join-Path $PgBin "pg_dump.exe") -h $uri.Host -p $uri.Port -U $user -F c -f (Join-Path $dest "database.dump") $db
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }
Remove-Item Env:\PGPASSWORD

foreach ($dir in "media", "private_media") {
    $src = Join-Path $root "backend\$dir"
    if (Test-Path $src) { Compress-Archive -Path "$src\*" -DestinationPath (Join-Path $dest "$dir.zip") -Force }
}
Get-ChildItem (Join-Path $root "backups") -Directory | Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-$KeepDays) } | Remove-Item -Recurse -Force
Write-Host "Backup written to $dest" -ForegroundColor Green
Write-Host "Copy backups off this machine (e.g. encrypted cloud storage) - a local copy alone is not a backup."
