@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"

set "AUDIT_PS=%PROJECT_ROOT%\scripts\powershell\audit_cv_preview.ps1"
if not exist "%AUDIT_PS%" (
  echo [ERROR] File not found: "%AUDIT_PS%"
  exit /b 1
)

set "ARGS="
if /I "%~1"=="--fix" set "ARGS=-Fix"

powershell -NoProfile -ExecutionPolicy Bypass -File "%AUDIT_PS%" %ARGS%
exit /b %ERRORLEVEL%
