# Starts the Django API on http://127.0.0.1:8000 and the background job worker.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\start-backend.ps1 [-NoWorker]
param([switch]$NoWorker)
$backend = Join-Path (Split-Path -Parent $PSScriptRoot) "backend"
Set-Location $backend
if (-not $NoWorker) {
    # Rent charges, reminders, reservation expiry, scheduled notices and retries (every 5 minutes)
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "manage.py", "run_worker", "--interval", "300" -WindowStyle Minimized
    Write-Host "Background worker started in a minimised window."
}
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
