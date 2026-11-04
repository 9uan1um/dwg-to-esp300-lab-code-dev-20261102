# Shared by the launcher and package builder. No system Python, WSL or admin required.
function Get-FlwRequirementsHash {
    $hash = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [IO.File]::ReadAllBytes((Join-Path (Split-Path -Parent $PSScriptRoot) 'requirements.txt'))
        return [BitConverter]::ToString($hash.ComputeHash($bytes)).Replace('-', '')
    } finally { $hash.Dispose() }
}

function Get-FlwPython {
    $appRoot = Split-Path -Parent $PSScriptRoot
    $python = Join-Path $appRoot 'runtime\python.exe'
    $marker = Join-Path $appRoot 'runtime\requirements.sha256'
    $expected = Get-FlwRequirementsHash
    if (-not (Test-Path -LiteralPath $python)) {
        # This dated copy reuses the user's existing runtime without installation.
        $trustedRoot = Join-Path (Split-Path -Parent $appRoot) 'dwg-to-esp300-lab-code-dev-20261028'
        $python = Join-Path $trustedRoot 'runtime\python.exe'
        $marker = Join-Path $trustedRoot 'runtime\requirements.sha256'
        if (-not (Test-Path -LiteralPath $python)) { throw 'Existing trusted runtime is missing; no installation was attempted.' }
    }
    if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne $expected) {
        throw 'Runtime is incomplete or requirements changed. Rename runtime to runtime-old, then run dwg-esp300-launch.cmd again. See docs/quick-start.ko.md.'
    }
    return $python
}
