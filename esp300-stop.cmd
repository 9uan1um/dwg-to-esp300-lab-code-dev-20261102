@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_esp300.ps1"
set "esp300Exit=%errorlevel%"
popd
if not "%esp300Exit%"=="0" (
    echo.
    echo Could not stop every ESP300 server. Read the error above.
    if not defined ESP300_NO_PAUSE pause
)
exit /b %esp300Exit%
