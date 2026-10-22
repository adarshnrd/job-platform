# PowerShell runner for Job Platform
param (
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$RootDir = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $RootDir "apps\api"
$WebDir = Join-Path $RootDir "apps\web"

# Ensure .env
$RootEnv = Join-Path $RootDir ".env"
$RootEnvExample = Join-Path $RootDir ".env.example"
$ApiEnv = Join-Path $ApiDir ".env"
$WebEnv = Join-Path $WebDir ".env.local"

if (!(Test-Path $RootEnv) -and (Test-Path $RootEnvExample)) {
    Write-Host "⚠️  Copying .env from .env.example..." -ForegroundColor Yellow
    Copy-Item $RootEnvExample $RootEnv
}

if (Test-Path $RootEnv) {
    if (!(Test-Path $ApiEnv)) { Copy-Item $RootEnv $ApiEnv }
    if (!(Test-Path $WebEnv)) { Copy-Item $RootEnv $WebEnv }
}

# Find Python
$PythonCmd = "python"
if (Test-Path (Join-Path $ApiDir "venv\Scripts\python.exe")) {
    $PythonCmd = Join-Path $ApiDir "venv\Scripts\python.exe"
} elseif (Test-Path (Join-Path $ApiDir ".venv\Scripts\python.exe")) {
    $PythonCmd = Join-Path $ApiDir ".venv\Scripts\python.exe"
}

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "🚀 Starting Job Platform Dev Servers..." -ForegroundColor Cyan
Write-Host "Backend Python:  $PythonCmd"
Write-Host "Frontend Runner: npm"
Write-Host "==============================================" -ForegroundColor Cyan

$jobs = @()

if (!$FrontendOnly) {
    Write-Host "⚡ [API] Starting FastAPI on http://localhost:8000 (docs: http://localhost:8000/docs)..." -ForegroundColor Green
    $jobs += Start-Process -FilePath $PythonCmd -ArgumentList "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload" -WorkingDirectory $ApiDir -PassThru
}

if (!$BackendOnly) {
    Write-Host "⚡ [WEB] Starting Next.js on http://localhost:3000..." -ForegroundColor Magenta
    $jobs += Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm", "run", "dev" -WorkingDirectory $WebDir -PassThru
}

Write-Host "`nPress Ctrl+C or close this window to stop servers.`n" -ForegroundColor Yellow

try {
    # Keep script open and wait
    $jobs | Wait-Process
} finally {
    Write-Host "`n🛑 Stopping servers..." -ForegroundColor Red
    foreach ($j in $jobs) {
        if ($j -and !$j.HasExited) {
            Stop-Process -Id $j.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
