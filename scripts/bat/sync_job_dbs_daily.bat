@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
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

echo.
echo === Job DB Daily Sync ===
echo Project root: %PROJECT_ROOT%
echo.

"%PYTHON_EXE%" %PYTHON_ARGS% "%PROJECT_ROOT%\scripts\python\sync_job_databases_safe.py" ^
  --source "%PROJECT_ROOT%\input\crawled_job\linkedin_jobs_jd.sqlite" ^
  --target "%PROJECT_ROOT%\apps\backend\app\job_ops_schema.sqlite" ^
  --skip-if-source-active

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo [ERROR] Daily DB sync failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

echo [OK] Daily DB sync finished.
exit /b 0
