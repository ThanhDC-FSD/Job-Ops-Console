@echo off
setlocal

rem ------------------------------------------------------------------
rem Manual sync helper for the crawl DB (dev) and API/CD schema copy.
rem Usage:
rem   sync_job_dbs.bat                    -> sync dev -> cd
rem   sync_job_dbs.bat cd-to-dev          -> sync cd -> dev
rem   sync_job_dbs.bat dev-to-cd          -> force dev -> cd (default)
rem   sync_job_dbs.bat dev-to-cd --yes    -> sync without confirmation
rem ------------------------------------------------------------------

set "DEV_DB=input\crawled_job\linkedin_jobs_jd.sqlite"
set "CD_DB=apps\backend\app\job_ops_schema.sqlite"
for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
set "PYTHON_EXE=C:\Python313\python.exe"
set "PYTHON_ARGS=-E"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
  set "PYTHON_ARGS="
)
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
  set "PYTHON_ARGS="
)
set "SYNC_SCRIPT=%~dp0\..\python\sync_job_databases_safe.py"
set "AUTO_YES=0"
if /i "%~2"=="--yes" set "AUTO_YES=1"
if /i "%~1"=="--yes" (
  set "AUTO_YES=1"
  set "SOURCE=%DEV_DB%"
  set "TARGET=%CD_DB%"
  set "DIRECTION=Dev -> CD"
)

if /i "%~1"=="cd-to-dev" (
  set "SOURCE=%CD_DB%"
  set "TARGET=%DEV_DB%"
  set "DIRECTION=CD -> Dev"
) else (
  set "SOURCE=%DEV_DB%"
  set "TARGET=%CD_DB%"
  set "DIRECTION=Dev -> CD"
)

echo.
echo === Job DB Sync Helper ===
echo Direction: %DIRECTION%
echo Source    : %SOURCE%
echo Target    : %TARGET%
echo.
if "%AUTO_YES%"=="0" (
  choice /m "Proceed with the sync (this will overwrite the target)?" /n >nul
  if errorlevel 2 (
    echo Sync cancelled.
    exit /b 1
  )
)

echo Running safe SQLite sync --source "%SOURCE%" --target "%TARGET%"
"%PYTHON_EXE%" %PYTHON_ARGS% "%SYNC_SCRIPT%" --source "%SOURCE%" --target "%TARGET%"
if %errorlevel% neq 0 (
  echo [ERROR] sync_job_dbs failed with exit code %errorlevel%.
  exit /b %errorlevel%
)

echo.
echo Sync completed. Source (latest write): %SOURCE%
echo Target replaced with the copied file.
endlocal
