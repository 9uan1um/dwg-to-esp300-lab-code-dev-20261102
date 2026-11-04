@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_portable.ps1"
set "flwExit=%errorlevel%"
popd
if not "%flwExit%"=="0" if not defined ESP300_NO_PAUSE pause
exit /b %flwExit%
