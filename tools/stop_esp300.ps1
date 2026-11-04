# Stop the ESP300 application servers only. No motor commands are sent.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot

try {
    $run = Invoke-RestMethod 'http://127.0.0.1:8768/api/run/status' -TimeoutSec 2
    if ($run.running) { throw 'A machine job is running. Stop physical motion first, then run this command again.' }
} catch {
    if ($_.Exception.Message -like '*machine job is running*') { throw }
}

foreach ($port in @(8768, 18768)) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    foreach ($serverPid in @($listeners.OwningProcess | Select-Object -Unique)) {
        if (-not $serverPid) { continue }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
        if ($process.Name -notmatch '^python(w)?\.exe$' -or $process.CommandLine -notmatch 'visualizer_server') {
            throw "Refusing to stop an unidentified process on port $port."
        }
        try {
            Invoke-RestMethod "http://127.0.0.1:$port/api/server/stop" -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 3 | Out-Null
        } catch {
            if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 400) {
                throw 'Server refused shutdown because a machine operation is running. Stop physical motion first.'
            }
            # Legacy/unresponsive versions may not implement graceful shutdown.
        }
        $deadline = (Get-Date).AddSeconds(4)
        while ((Get-Process -Id $serverPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 100
        }
        if (Get-Process -Id $serverPid -ErrorAction SilentlyContinue) {
            Stop-Process -Id $serverPid -ErrorAction Stop
        }
        Write-Output "Stopped ESP300 web/preview server on $port (PID $serverPid)."
    }
}

# Do not wake a stopped distribution solely to stop a nonexistent bridge.
$runningDistros = @()
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    # WSL may be absent, disabled, or unconfigured on a native-Windows PC.
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $runningDistros = @((& wsl.exe --list --running --quiet 2>$null) -replace "`0", '')
        if ($LASTEXITCODE -ne 0) { $runningDistros = @() }
    } finally { $ErrorActionPreference = $savedPreference }
}
if ($runningDistros -contains 'FLW-ESP300') {
    & wsl.exe -d FLW-ESP300 -u flw --cd $repo -- python3 tools/esp300_bridge_runtime.py --stop-server
    if ($LASTEXITCODE -ne 0) { throw 'Could not stop the identified ESP300 bridge.' }
}
foreach ($port in @(8768, 18768)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "A server is still listening on port $port."
    }
}
Write-Output 'ESP300 web server and bridge are stopped. No motor-enable/disable commands were sent.'
