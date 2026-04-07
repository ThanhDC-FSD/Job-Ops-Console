@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "TARGET=%PROJECT_ROOT%\scripts\python\linkedin_jobs_applied_tracker.py"

if not exist "%VENV_PY%" (
  echo [ERROR] Virtual environment not found at "%PROJECT_ROOT%\.venv"
  echo Please run: python -m venv .venv
  exit /b 1
)

if not exist "%TARGET%" (
  echo [ERROR] File not found: "%TARGET%"
  exit /b 1
)

set PYTHONHOME=
set PYTHONPATH=

pushd "%PROJECT_ROOT%"
"%VENV_PY%" "%TARGET%" %*
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Script exited with error code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
