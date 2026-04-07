@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=C:\Python313\python.exe"
set "PY_ARGS=-E"
if not exist "%VENV_PY%" (
  set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
  set "PY_ARGS="
)
if not exist "%VENV_PY%" (
  set "VENV_PY=python"
  set "PY_ARGS="
)
set "DEV_DB=%PROJECT_ROOT%\input\crawled_job\linkedin_jobs_jd.sqlite"
set "CD_DB=%PROJECT_ROOT%\apps\backend\app\job_ops_schema.sqlite"

if not exist "%VENV_PY%" (
  echo [ERROR] %VENV_PY% not found.
  exit /b 1
)

set "TIMESTAMP="
for /f "usebackq" %%T in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd_HHmmss'"`) do set "TIMESTAMP=%%T"
set "BACKUP_DIR=%PROJECT_ROOT%\backups\db_sync\%TIMESTAMP%"
set "DEV_BACKUP=%BACKUP_DIR%\dev_pre_sync.sqlite"
set "CD_BACKUP=%BACKUP_DIR%\cd_pre_sync.sqlite"

echo.
echo === Database Sync with Backup ===
echo Backups will be stored under %BACKUP_DIR%
mkdir "%BACKUP_DIR%" >nul 2>&1

echo.
echo [STEP] Backing up Dev DB
"%VENV_PY%" %PY_ARGS% "%PROJECT_ROOT%\scripts\python\db_backup.py" --source "%DEV_DB%" --target "%DEV_BACKUP%"

echo.
echo [STEP] Backing up CD DB
"%VENV_PY%" %PY_ARGS% "%PROJECT_ROOT%\scripts\python\db_backup.py" --source "%CD_DB%" --target "%CD_BACKUP%"

echo.
set "DIRECTION=%~1"
if /i "%DIRECTION%"=="cd-to-dev" (
  set "SYNC_ARG=cd-to-dev"
) else (
  set "SYNC_ARG=dev-to-cd"
)

echo [STEP] Running sync_job_dbs.bat %SYNC_ARG% --yes
call "%SCRIPT_DIR%sync_job_dbs.bat" %SYNC_ARG% --yes
if errorlevel 1 (
  echo [ERROR] Sync script failed. Aborting comparison.
  exit /b %ERRORLEVEL%
)

echo.
echo [STEP] Comparing snapshots
"%VENV_PY%" %PY_ARGS% "%PROJECT_ROOT%\scripts\python\db_compare.py" --dev-before "%DEV_BACKUP%" --cd-before "%CD_BACKUP%" --dev-after "%DEV_DB%" --cd-after "%CD_DB%"

echo.
echo Sync and verification complete.
endlocal
