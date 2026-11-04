param([string]$LogDirectory = (Join-Path $PSScriptRoot '..\outputs\esp300-virtualization'))
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this setup script as administrator. No driver downgrade is performed.'
}
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$resultPath = Join-Path $LogDirectory 'setup-result.json'
$result = @{ status = 'running'; restartRequired = $false; started = (Get-Date).ToString('o') }
if (Test-Path -LiteralPath $resultPath) {
    $previous = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    $result.restartRequired = [bool]$previous.restartRequired
}
$result | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
Start-Transcript -Path (Join-Path $LogDirectory 'setup.log') -Append
try {
    & pnputil.exe /enum-drivers /class Ports | Set-Content -LiteralPath (Join-Path $LogDirectory 'ports-drivers-before.txt') -Encoding utf8

    $feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    Write-Output "VirtualMachinePlatform before: $($feature.State)"
    if ($feature.State -ne 'Enabled') {
        $enabled = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
        $result.restartRequired = $result.restartRequired -or [bool]$enabled.RestartNeeded
    }

    # Package sources/versions were checked against their official releases.
    if (-not (Get-AppxPackage 'MicrosoftCorporationII.WindowsSubsystemForLinux')) {
        & winget install --id Microsoft.WSL --version 2.7.14 --exact --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) { throw "WSL installation exit code: $LASTEXITCODE" }
    }
    & winget install --id dorssel.usbipd-win --version 5.3.0 --exact --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity --override '/quiet /norestart REBOOT=ReallySuppress'
    if ($LASTEXITCODE -eq 3010) { $result.restartRequired = $true }
    elseif ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { throw "usbipd installation exit code: $LASTEXITCODE" }

    & pnputil.exe /enum-drivers /class Ports | Set-Content -LiteralPath (Join-Path $LogDirectory 'ports-drivers-after.txt') -Encoding utf8
    $result.status = 'installed'
} catch {
    $result.status = 'failed'
    $result.error = $_.Exception.Message
    Write-Output $result.error
} finally {
    $result.finished = (Get-Date).ToString('o')
    $result | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding utf8
    Stop-Transcript
}
if ($result.status -eq 'failed') { exit 1 }
