@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"

set "TASK_NAME=JobOps_Daily_DbSync"
set "TASK_TIME=23:15"
if not "%~1"=="" set "TASK_TIME=%~1"

set "TASK_SCRIPT=%PROJECT_ROOT%\scripts\bat\sync_job_dbs_daily.bat"
if not exist "%TASK_SCRIPT%" (
  echo [ERROR] Task script not found: "%TASK_SCRIPT%"
  exit /b 1
)

set "TASK_CMD=\"%TASK_SCRIPT%\""

echo.
echo === Install Daily DB Sync Task ===
echo Task name : %TASK_NAME%
echo Time      : %TASK_TIME%
echo Command   : %TASK_CMD%
echo.

schtasks /Create /TN "%TASK_NAME%" /TR "%TASK_CMD%" /SC DAILY /ST %TASK_TIME% /F
if errorlevel 1 (
  echo [ERROR] Failed to create scheduled task "%TASK_NAME%".
  exit /b 1
)

echo [OK] Scheduled task created: %TASK_NAME%
schtasks /Query /TN "%TASK_NAME%" /V /FO LIST

exit /b 0
