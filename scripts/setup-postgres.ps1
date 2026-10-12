# Creates the PostgreSQL role and database and points backend\.env at it.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup-postgres.ps1
# You will be asked for the password of the PostgreSQL superuser ("postgres")
# chosen when PostgreSQL was installed, and for a new password for the app role.
param(
    [string]$PsqlPath = "C:\Program Files\PostgreSQL\17\bin\psql.exe",
    [string]$DbName = "propman",
    [string]$DbUser = "propman",
    [string]$DbHost = "localhost",
    [int]$Port = 5432
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $PsqlPath)) {
    $found = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1
    if (-not $found) { throw "psql.exe not found. Install PostgreSQL or pass -PsqlPath." }
    $PsqlPath = $found.FullName
}
$superPw = Read-Host "Password for PostgreSQL user 'postgres'" -AsSecureString
$appPw = Read-Host "New password for application role '$DbUser'" -AsSecureString
$plainSuper = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($superPw))
$plainApp = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($appPw))
if ($plainApp -match "[':@/ ]") { throw "Please use an app password without quotes, colons, @, / or spaces." }

$env:PGPASSWORD = $plainSuper
$sql = @"
DO `$`$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DbUser') THEN
    CREATE ROLE $DbUser LOGIN PASSWORD '$plainApp';
  ELSE
    ALTER ROLE $DbUser WITH LOGIN PASSWORD '$plainApp';
  END IF;
END `$`$;
"@
& $PsqlPath -U postgres -h $DbHost -p $Port -v ON_ERROR_STOP=1 -c $sql
$exists = & $PsqlPath -U postgres -h $DbHost -p $Port -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'"
if ($exists -ne "1") { & $PsqlPath -U postgres -h $DbHost -p $Port -v ON_ERROR_STOP=1 -c "CREATE DATABASE $DbName OWNER $DbUser ENCODING 'UTF8'" }
Remove-Item Env:\PGPASSWORD

$envFile = Join-Path (Split-Path -Parent $PSScriptRoot) "backend\.env"
$url = "DATABASE_URL=postgres://${DbUser}:${plainApp}@${DbHost}:${Port}/${DbName}"
$lines = Get-Content $envFile | Where-Object { $_ -notmatch "^\s*#?\s*DATABASE_URL=" }
($lines + $url) | Set-Content $envFile -Encoding utf8
Write-Host "PostgreSQL ready and backend\.env updated." -ForegroundColor Green
Write-Host "Next: cd backend; .\.venv\Scripts\python.exe manage.py migrate; .\.venv\Scripts\python.exe manage.py setup_defaults; .\.venv\Scripts\python.exe manage.py seed_demo"
