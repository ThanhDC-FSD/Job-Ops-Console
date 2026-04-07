@echo off
setlocal
title JobOps_Frontend_Dev
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "APP_DIR=%PROJECT_ROOT%\apps\frontend"
set "VITE_API_BASE=http://127.0.0.1:8102"
pushd "%APP_DIR%"
if not exist node_modules (
  call npm install
)
call npm run dev -- --host 127.0.0.1 --port 5182
set "EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %EXIT_CODE%
