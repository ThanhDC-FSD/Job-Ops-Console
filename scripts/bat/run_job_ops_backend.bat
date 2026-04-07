@echo off
setlocal
title JobOps_Backend_Dev
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "APP_DIR=%PROJECT_ROOT%\apps\backend"
set "OPENAI_BASE_URL=http://127.0.0.1:8102/v1"
set "OPENAI_ALLOW_NO_KEY=1"
set PYTHONHOME=
set PYTHONPATH=
set PYTHONSTARTUP=
set PYTHONNOUSERSITE=1
if not exist "%VENV_PY%" (
  echo [ERROR] Python venv not found: %VENV_PY%
  exit /b 1
)
echo [INFO] Validating Python runtime...
"%VENV_PY%" -I -c "import re" >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo [ERROR] Python runtime is broken ^(likely SRE module mismatch^).
  echo [HINT] Recreate venv:
  echo        rmdir /s /q .venv
  echo        C:\Python313\python.exe -m venv .venv
  echo        .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
echo [INFO] Python runtime OK.
pushd "%APP_DIR%"
"%VENV_PY%" -I -m uvicorn app.main:app --host 127.0.0.1 --port 8102
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
