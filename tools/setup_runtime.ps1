# Application-local runtime. The distributed portable ZIP already contains it.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$appRoot = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $appRoot 'runtime'
if (Test-Path -LiteralPath $destination) { throw 'runtime already exists. Rename it before rebuilding.' }
if (-not [Environment]::Is64BitOperatingSystem) { throw 'FLW requires 64-bit Windows.' }
$stage = Join-Path $appRoot ('.runtime-setup-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    Write-Host 'First launch: downloading application-local Python and libraries. Internet required once.'
    $archive = Join-Path $stage 'python.zip'
    $pythonUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
    Invoke-WebRequest -UseBasicParsing -Uri $pythonUrl -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $stage
    Remove-Item -LiteralPath $archive
    # Paths are relative to python.exe, so moving the complete app folder works.
    @('python312.zip', '.', 'Lib/site-packages', '..', 'import site') | Set-Content -LiteralPath (Join-Path $stage 'python312._pth') -Encoding ascii
    $pipTool = Join-Path $stage 'pip.pyz'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://bootstrap.pypa.io/pip/pip.pyz' -OutFile $pipTool
    & (Join-Path $stage 'python.exe') $pipTool --isolated install --disable-pip-version-check --only-binary=:all: --no-compile --target (Join-Path $stage 'Lib\site-packages') -r (Join-Path $appRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Library download/install failed.' }
    Remove-Item -LiteralPath $pipTool
    & (Join-Path $stage 'python.exe') (Join-Path $PSScriptRoot 'check_environment.py')
    if ($LASTEXITCODE -ne 0) { throw 'Application import check failed.' }
    . (Join-Path $PSScriptRoot 'flw_runtime.ps1')
    Get-FlwRequirementsHash | Set-Content -LiteralPath (Join-Path $stage 'requirements.sha256') -Encoding ascii
    Move-Item -LiteralPath $stage -Destination $destination
    Write-Host 'Application runtime ready. Future launches need no internet.'
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)"
    throw 'Check the internet connection and available disk space, then retry. No Windows drivers or WSL settings were changed.'
} finally {
    # Only this invocation's exact staging directory may be removed.
    $resolvedRoot = [IO.Path]::GetFullPath($appRoot).TrimEnd('\') + '\'
    $resolvedStage = [IO.Path]::GetFullPath($stage)
    if ($resolvedStage.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolvedStage) -like '.runtime-setup-*' -and (Test-Path -LiteralPath $resolvedStage)) {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}
