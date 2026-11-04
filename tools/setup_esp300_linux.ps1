# Run after the Windows feature restart. USB may remain unplugged.
$ErrorActionPreference = 'Stop'
$distro = 'FLW-ESP300'
$repo = Split-Path -Parent $PSScriptRoot
$installed = (& wsl.exe --list --quiet 2>$null) -replace "`0", ''
if ($installed -notcontains $distro) {
    & wsl.exe --install Ubuntu-24.04 --name $distro --no-launch --web-download
    if ($LASTEXITCODE -ne 0) { throw 'Ubuntu installation did not finish. Check the WSL output above.' }
    $installed = (& wsl.exe --list --quiet 2>$null) -replace "`0", ''
    if ($installed -notcontains $distro) { throw 'The distribution is not registered yet. Restart Windows, then run this script again.' }
}
& wsl.exe -d $distro -u root --cd $repo -- bash tools/setup_esp300_linux.sh
if ($LASTEXITCODE -ne 0) { throw 'Linux prerequisites failed. Check the output above.' }
& wsl.exe --manage $distro --set-default-user flw
if ($LASTEXITCODE -ne 0) { throw 'Could not set the dedicated Linux user.' }
Write-Output 'Linux setup finished. Next: attach the USB adapter and start the serial bridge.'
