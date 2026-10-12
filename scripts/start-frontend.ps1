# Starts the Angular dev server on http://localhost:4200 (proxies /api and /media to Django).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-frontend.ps1
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "frontend")
npx ng serve --port 4200
