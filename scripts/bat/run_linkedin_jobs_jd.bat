@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "TARGET=%PROJECT_ROOT%\scripts\python\linkedin_jobs_jd.py"

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
set "HAS_MODE="
for %%A in (%*) do (
  if /I "%%~A"=="--mode" set "HAS_MODE=1"
)

pushd "%PROJECT_ROOT%"
if defined HAS_MODE (
  "%VENV_PY%" "%TARGET%" %*
) else (
  "%VENV_PY%" "%TARGET%" --mode api %*
)
popd
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Script exited with error code %EXIT_CODE%.
)

exit /b %EXIT_CODE%

rem run_linkedin_jobs_jd.bat --window-days 30 --max-jobs 500
rem run_linkedin_jobs_jd.bat --window-days 30 
rem run_linkedin_jobs_jd.bat 
