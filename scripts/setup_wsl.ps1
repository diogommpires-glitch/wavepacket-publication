param([switch]$SkipDistribution)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$setupDirectory = Join-Path $projectRoot "results\setup"
New-Item -ItemType Directory -Path $setupDirectory -Force | Out-Null
$statusFile = Join-Path $setupDirectory "wsl-status.json"
$logFile = Join-Path $setupDirectory "wsl-install.log"

function Save-Stage([string]$Stage, [string]$Message, [bool]$RestartRequired = $false) {
    $record = @{stage=$Stage;message=$Message;restart_required=$RestartRequired;
        updated_utc=[DateTime]::UtcNow.ToString("o");distribution="Ubuntu-24.04"}
    $record | ConvertTo-Json | Set-Content -LiteralPath $statusFile -Encoding utf8
    Write-Output "$Stage : $Message"
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Save-Stage "requires_administrator" "Run this script from an elevated PowerShell. No changes made."
    exit 10
}

Start-Transcript -Path $logFile -Append | Out-Null
try {
    Save-Stage "checking_features" "Checking Windows virtualization and WSL components."
    $restartRequired = $false
    foreach ($featureName in @("Microsoft-Windows-Subsystem-Linux", "VirtualMachinePlatform")) {
        $feature = Get-WindowsOptionalFeature -Online -FeatureName $featureName
        if ($feature.State -eq "Disabled") {
            Save-Stage "enabling_features" "Enabling $featureName without restarting Windows."
            $operation = Enable-WindowsOptionalFeature -Online -FeatureName $featureName -All -NoRestart
            $restartRequired = $restartRequired -or $operation.RestartNeeded
        } elseif ($feature.State -eq "EnablePending") {
            $restartRequired = $true
        }
    }
    if ($restartRequired) {
        Save-Stage "restart_required" "Windows features are enabled. Restart when ready, then run this script again." $true
        exit 3010
    }
    Save-Stage "installing_runtime" "Installing the Microsoft WSL runtime without launching a distribution."
    & wsl.exe --install --no-distribution --no-launch --web-download
    if ($LASTEXITCODE -ne 0) {
        throw "WSL runtime installation returned $LASTEXITCODE. See wsl-install.log."
    }
    & wsl.exe --set-default-version 2
    if ($LASTEXITCODE -ne 0) { throw "Could not select WSL2 as the default." }
    if (-not $SkipDistribution) {
        Save-Stage "installing_distribution" "Installing Ubuntu 24.04 LTS without launching it."
        $installed = ((& wsl.exe --list --quiet) -join "`n") -replace '\x00', ''
        if ($installed -notmatch "Ubuntu-24.04") {
            & wsl.exe --install --distribution Ubuntu-24.04 --no-launch --web-download
            if ($LASTEXITCODE -ne 0) { throw "Ubuntu installation returned $LASTEXITCODE." }
        }
    }
    Save-Stage "ready_for_first_launch" "WSL2 is installed. Launch Ubuntu-24.04 and create the normal Linux user locally."
} catch {
    Save-Stage "failed" $_.Exception.Message
    throw
} finally {
    Stop-Transcript | Out-Null
}
