$ErrorActionPreference = "Stop"
$installerPath = Join-Path $PSScriptRoot "setup_wsl.ps1"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    & $installerPath
    exit $LASTEXITCODE
}
# This launcher is interactive: Windows must show its administrator prompt.
$installerArguments = @('-NoProfile','-NoExit','-ExecutionPolicy','Bypass','-File',('"{0}"' -f $installerPath))
Start-Process -FilePath 'powershell.exe' -ArgumentList $installerArguments -Verb RunAs
