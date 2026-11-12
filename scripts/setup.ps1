param([string]$Python = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
New-Item -ItemType Directory -Path "tmp" -Force | Out-Null
$candidatePaths = @(
    $Python,
    $env:WAVEPACKET_PYTHON,
    "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    (Get-Command python -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
$selectedPython = $null
foreach ($candidatePath in $candidatePaths) {
    $versionCheck = & $candidatePath -c "import sys; print('yes' if sys.version_info[:2] == (3,12) else 'no')"
    if ($versionCheck -eq "yes") { $selectedPython = $candidatePath; break }
}
if (-not $selectedPython) { throw "Python 3.12 is required. Run scripts/setup.ps1 -Python C:\path\to\python.exe" }
$environmentPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $environmentPython)) {
    & $selectedPython -m venv --without-pip .venv
    if ($LASTEXITCODE -ne 0) { throw "Environment creation failed" }
}
& $selectedPython -m pip --python $environmentPython install pip hatchling editables
if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed" }
if (Test-Path -LiteralPath "requirements-lock.txt") {
    & $environmentPython -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw "Locked dependency installation failed" }
}
& $environmentPython -m pip install --no-build-isolation -e ".[dev,notebooks]"
if ($LASTEXITCODE -ne 0) { throw "Package installation failed" }
Push-Location frontend
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
} finally { Pop-Location }
& $environmentPython scripts/build_frontend.py
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
Write-Host "Ready. Run .\Start-Wavepacket.cmd or .venv\Scripts\wavepacket.exe serve --open-browser"
