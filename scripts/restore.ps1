# Restores a backup created by scripts\backup.ps1.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\restore.ps1 -BackupDir backups\20261012-020000
# WARNING: replaces the current database contents and uploaded files.
param([Parameter(Mandatory = $true)][string]$BackupDir, [string]$PgBin = "C:\Program Files\PostgreSQL\17\bin")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$answer = Read-Host "This will OVERWRITE the current database and files. Type RESTORE to continue"
if ($answer -ne "RESTORE") { Write-Host "Cancelled."; exit 1 }
$line = Get-Content (Join-Path $root "backend\.env") | Where-Object { $_ -match "^DATABASE_URL=" } | Select-Object -First 1
$uri = [Uri]($line -replace "^DATABASE_URL=", "")
$user, $pass = $uri.UserInfo.Split(":", 2)
$db = $uri.AbsolutePath.TrimStart("/")
$env:PGPASSWORD = [Uri]::UnescapeDataString($pass)
& (Join-Path $PgBin "pg_restore.exe") -h $uri.Host -p $uri.Port -U $user -d $db --clean --if-exists --no-owner (Join-Path $BackupDir "database.dump")
Remove-Item Env:\PGPASSWORD
foreach ($dir in "media", "private_media") {
    $zip = Join-Path $BackupDir "$dir.zip"
    if (Test-Path $zip) { Expand-Archive -Path $zip -DestinationPath (Join-Path $root "backend\$dir") -Force }
}
Write-Host "Restore complete. Restart the backend." -ForegroundColor Green
