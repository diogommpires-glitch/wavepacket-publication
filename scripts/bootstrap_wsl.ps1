param([string]$Distribution = "Ubuntu-24.04")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$installed = ((& wsl.exe --list --quiet) -join "`n") -replace '\x00', ''
if ($LASTEXITCODE -ne 0 -or $installed -notmatch [regex]::Escape($Distribution)) {
    throw "Ubuntu is not installed yet. Complete Setup-Linux.cmd, restart if required, then run it again."
}
$linuxUser = ([string](& wsl.exe --distribution $Distribution --exec id -un)).Trim()
if ($LASTEXITCODE -ne 0 -or $linuxUser -eq "root") {
    throw "Launch Ubuntu-24.04 first and create the normal Linux user locally."
}
& git rev-parse --verify HEAD
if ($LASTEXITCODE -ne 0) { throw "Commit the reviewed source before creating the independent Linux checkout." }
$mountedProject = ([string](& wsl.exe --distribution $Distribution --exec wslpath -a $projectRoot)).Trim()
if ($LASTEXITCODE -ne 0 -or -not $mountedProject) { throw "Could not resolve the Windows source path inside WSL." }
& wsl.exe --distribution $Distribution --user root --exec bash "$mountedProject/scripts/setup_linux.sh" --system
if ($LASTEXITCODE -ne 0) { throw "Linux system dependency installation failed." }
$linuxHome = ([string](& wsl.exe --distribution $Distribution --exec printenv HOME)).Trim()
if ($LASTEXITCODE -ne 0 -or -not $linuxHome.StartsWith("/")) { throw "Could not resolve the normal Linux user's home directory." }
$linuxProject = "$linuxHome/src/wavepacket-lab"
& wsl.exe --distribution $Distribution --exec bash "$mountedProject/scripts/bootstrap_linux.sh" $mountedProject $linuxProject
if ($LASTEXITCODE -ne 0) { throw "Linux checkout creation/update failed; an existing modified checkout is preserved." }
& wsl.exe --distribution $Distribution --exec bash "$linuxProject/scripts/setup_linux.sh" --user
if ($LASTEXITCODE -ne 0) { throw "Linux user environment setup failed." }
& wsl.exe --distribution $Distribution --user root --exec "$linuxHome/.local/share/wavepacket-node/current/bin/node" "$linuxProject/frontend/node_modules/playwright/cli.js" install-deps chromium
if ($LASTEXITCODE -ne 0) { throw "Linux browser system dependencies failed." }
Write-Output "Linux checkout ready: $linuxProject"
Write-Output "Run WSL tests there with .venv/bin/python -m pytest --basetemp=tmp/pytest"
