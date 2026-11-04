param([switch]$Check, [switch]$NoBrowser, [ValidateRange(1024,65535)][int]$Port = 8768)
# Run the web server in this terminal so Ctrl+C owns its lifetime.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'tools\flw_runtime.ps1')
$projectPython = Get-FlwPython
Set-Location -LiteralPath $root
if ($Check) {
    & $projectPython -u tools/check_environment.py
    if ($LASTEXITCODE -ne 0) { throw 'Application check failed. See the error above.' }
    exit 0
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    throw "A server already uses port $Port. Stop it in its owner CMD window with Ctrl+C, or run esp300-stop.cmd first."
}
$serverArgs = @('-u', (Join-Path $root 'visualizer_server.py'), '--host', '127.0.0.1', '--port', $Port)
if (-not $NoBrowser) { $serverArgs += '--open-browser' }
Write-Output 'Windows COM connections work directly. WSL is optional; start esp300-bridge.cmd only when needed.'
Write-Output 'Starting ESP300 web server in this window. Keep it open; Ctrl+C stops it.'
& $projectPython @serverArgs
if ($LASTEXITCODE -ne 0) { throw "Web server exited with code $LASTEXITCODE." }
