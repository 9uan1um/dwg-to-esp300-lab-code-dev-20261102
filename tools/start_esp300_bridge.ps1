param([ValidatePattern('^\d+-\d+(\.\d+)*$')][string]$BusId, [switch]$PrepareOnly)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
# Run in an interactive Windows PowerShell 5.1 or PowerShell 7 terminal.
# The adapter is auto-detected; first-time sharing requests administrator approval.
# This terminal owns the bridge. Never silently reuse a background process.
# Compatible with Windows PowerShell 5.1 and PowerShell 7. No motion commands.
$ErrorActionPreference = 'Stop'
$distro = 'FLW-ESP300'
$repo = Split-Path -Parent $PSScriptRoot
$usbipd = Join-Path $env:ProgramFiles 'usbipd-win\usbipd.exe'
if (-not (Test-Path -LiteralPath $usbipd)) { throw 'Install usbipd-win first.' }

$usbState = (& $usbipd state | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0) { throw 'Could not read usbipd state.' }
$serialAdapters = @($usbState.Devices | Where-Object { $_.BusId -and $_.InstanceId -match '^USB\\VID_067B&PID_2303\\' })
if (-not $BusId) {
    if ($serialAdapters.Count -eq 0) {
        throw 'No 067b:2303 USB adapter is plugged in. Plug the PC-side USB cable in, then rerun this script.'
    }
    if ($serialAdapters.Count -ne 1) {
        throw "Multiple matching adapters: $($serialAdapters.BusId -join ', '). Rerun with -BusId and the intended ID."
    }
    $BusId = $serialAdapters[0].BusId
}
$adapter = @($serialAdapters | Where-Object { $_.BusId -eq $BusId })
if ($adapter.Count -ne 1 -or $adapter[0].InstanceId -notmatch '^USB\\VID_067B&PID_2303\\') {
    throw "BUSID $BusId is not the expected 067b:2303 serial adapter. Check usbipd list."
}
if (-not $adapter[0].PersistedGuid) {
    Write-Output "Registering USB $BusId for WSL. Approve the Windows administrator prompt."
    try {
        $binding = Start-Process -FilePath $usbipd -Verb RunAs -WindowStyle Hidden -ArgumentList @('bind','--busid',$BusId) -Wait -PassThru
    } catch { throw "USB sharing registration was not approved: $($_.Exception.Message)" }
    if ($binding.ExitCode -ne 0) { throw "USB sharing registration failed (exit $($binding.ExitCode))." }
}
Write-Output "Selected adapter: 067b:2303, BUSID $BusId"

Write-Output '[1/4] Starting WSL and loading the PL2303 driver...'
& wsl.exe -d $distro -u root -- modprobe pl2303
if ($LASTEXITCODE -ne 0) { throw 'Linux PL2303 driver is unavailable. Complete Linux setup first.' }
if (-not $adapter[0].ClientIPAddress) {
    Write-Output "[2/4] Attaching USB $BusId to WSL..."
    & $usbipd attach --wsl $distro --busid $BusId
    if ($LASTEXITCODE -ne 0) { throw 'USB attach failed. Check the bus ID and bind this adapter as administrator first.' }
}
else { Write-Output "[2/4] USB $BusId is already attached to WSL." }
& wsl.exe -d $distro -u root -- udevadm settle
if ($LASTEXITCODE -ne 0) { throw 'udev did not settle.' }
Write-Output '[3/4] Finding the Linux serial device...'
# Passing a script filename avoids PowerShell 5.1 stripping quotes from -c.
$deviceOutput = & wsl.exe -d $distro -u flw --cd $repo -- python3 tools/esp300_bridge_runtime.py --find-device
if ($LASTEXITCODE -ne 0) { throw 'Could not locate the Linux serial device. See the Python error above.' }
$device = ($deviceOutput | ConvertFrom-Json).device
if (-not $device -or $device -notmatch '^/dev/ttyUSB\d+$') { throw 'Could not uniquely locate the Linux serial device.' }
Write-Output "[4/4] Checking bridge port 22170 for $device..."
$serverOutput = & wsl.exe -d $distro -u flw --cd $repo -- python3 tools/esp300_bridge_runtime.py --check-server $device
if ($LASTEXITCODE -ne 0) { throw 'Could not check the existing bridge.' }
$server = $serverOutput | ConvertFrom-Json
if ($server.running) {
    if ($PrepareOnly -and $server.compatible) {
        Write-Output "Existing verified bridge ready: $device on 22170."
        exit 0
    }
    throw "A bridge/listener is already running on 22170. This window cannot control it. Stop the existing bridge with Ctrl+C in its owner window, or run esp300-stop.cmd, then start again. Details: $serverOutput"
}
if ($PrepareOnly) {
    $logFolder = Join-Path $repo 'logs'
    New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $outLog = Join-Path $logFolder "wsl-bridge-$stamp.out.log"
    $errLog = Join-Path $logFolder "wsl-bridge-$stamp.err.log"
    $bridgeProcess = Start-Process -FilePath 'wsl.exe' -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog -ArgumentList @('-d',$distro,'-u','flw','--cd',('"' + $repo + '"'),'--','python3','-u','tools/esp300_serial_bridge.py','--device',$device)
    $deadline = (Get-Date).AddSeconds(10)
    do {
        $readyOutput = & wsl.exe -d $distro -u flw --cd $repo -- python3 tools/esp300_bridge_runtime.py --check-server $device
        if ($LASTEXITCODE -eq 0) {
            $ready = $readyOutput | ConvertFrom-Json
            if ($ready.running -and $ready.compatible) {
                Write-Output "Background bridge ready: $device on 22170. Log: $errLog"
                exit 0
            }
        }
        if ($bridgeProcess.HasExited) { throw "Bridge startup failed. See $errLog" }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)
    throw "Bridge startup timed out. See $errLog"
}
Write-Output 'ESP300 BRIDGE RUNNING IN THIS WINDOW. Keep it open. Press Ctrl+C to stop.'
Write-Output "Forwarding $device to rfc2217://127.0.0.1:22170. Ctrl+C stops the bridge."
& wsl.exe -d $distro -u flw --cd $repo -- python3 tools/esp300_serial_bridge.py --device $device
if ($LASTEXITCODE -ne 0) { throw 'Serial bridge exited with an error.' }
