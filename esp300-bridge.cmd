@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
echo Starting the ESP300 bridge in this CMD window...
echo Keep this window open. Press Ctrl+C to stop the bridge.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_esp300_bridge.ps1" %*
set "esp300Exit=%errorlevel%"
popd
if not "%esp300Exit%"=="0" (
    echo.
    echo ESP300 bridge startup failed. Read the error above.
    if not defined ESP300_NO_PAUSE pause
)
if "%esp300Exit%"=="0" echo ESP300 bridge stopped.
exit /b %esp300Exit%
