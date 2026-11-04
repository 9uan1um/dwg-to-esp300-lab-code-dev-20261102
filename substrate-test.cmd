@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_substrate_mock.ps1" %*
if errorlevel 1 (
    echo Substrate startup failed. No automatic installation is performed.
    if not defined ESP300_NO_PAUSE pause
    exit /b 1
)
