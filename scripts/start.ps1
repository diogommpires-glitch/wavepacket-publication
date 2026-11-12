param([switch]$OpenBrowser)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
try {
    $existingApp = Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/health" -TimeoutSec 2
    if ($existingApp.application -in @("Wavepacket", "Wavepacket Lab")) {
        if ($OpenBrowser) { Start-Process "http://127.0.0.1:8765" }
        Write-Host "Wavepacket is already running at http://127.0.0.1:8765"
        exit 0
    }
} catch { }
$environmentPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $environmentPython)) { & "$PSScriptRoot\setup.ps1" }
$launchArguments = @("-m", "wavepacket", "serve")
if ($OpenBrowser) { $launchArguments += "--open-browser" }
& $environmentPython @launchArguments
exit $LASTEXITCODE
