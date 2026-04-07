@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_FILE=%STARTUP_DIR%\run_job_ops_all_startup.cmd"
set "TARGET_BAT=%PROJECT_ROOT%\scripts\bat\run_job_ops_all.bat"

if not exist "%TARGET_BAT%" (
  echo [ERROR] File not found: "%TARGET_BAT%"
  exit /b 1
)

if not exist "%STARTUP_DIR%" (
  mkdir "%STARTUP_DIR%" >nul 2>&1
)

(
  echo @echo off
  echo cd /d "%PROJECT_ROOT%"
  echo call "%TARGET_BAT%" start all
) > "%STARTUP_FILE%"

echo [INFO] Installed startup launcher:
echo        "%STARTUP_FILE%"
echo [INFO] Windows will run Job Ops on next logon.
exit /b 0
