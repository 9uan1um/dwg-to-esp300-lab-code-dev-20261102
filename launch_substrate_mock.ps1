param([switch]$Check, [switch]$NoBrowser, [ValidateRange(0,65535)][int]$Port = 0,
      [string]$PythonPath, [ValidateSet('mock','live')][string]$Mode = 'live')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Requested PythonPath does not exist. No installation was attempted.' }
    $runtime = (Resolve-Path -LiteralPath $PythonPath).Path
} else {
    $candidates = @(
        (Join-Path $root 'runtime\python.exe'),
        (Join-Path (Split-Path -Parent $root) 'dwg-to-esp300-lab-code-dev-20261028\runtime\python.exe'),
        (Join-Path $env:USERPROFILE 'Projects\FLW\dwg-to-esp300-lab-code-dev-20261028\runtime\python.exe')
    )
    $runtime = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $runtime) { throw 'No existing local Python runtime found. Supply -PythonPath to a trusted Python 3.10+ interpreter. No download or installation was attempted.' }
}
Write-Output "Runtime (read-only reuse): $runtime"
Write-Output 'Original app with integrated Substrate Test. Startup does not connect devices. No installation. Use -Mode mock for blocked hardware QA.'
$arguments = @('-B','-u',(Join-Path $root 'launch_integrated.py'),'--mode',$Mode,'--port',"$Port")
if ($Check) { $arguments += '--check' }
if ($NoBrowser) { $arguments += '--no-browser' }
Push-Location -LiteralPath $root
try {
    & $runtime @arguments
    if ($LASTEXITCODE -ne 0) { throw "Substrate application exited with code $LASTEXITCODE. Existing applications were not stopped." }
} finally { Pop-Location }


