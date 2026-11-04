$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'flw_runtime.ps1')
$python = Get-FlwPython
& $python (Join-Path $PSScriptRoot 'build_portable.py')
if ($LASTEXITCODE -ne 0) { throw 'Portable package build failed.' }
