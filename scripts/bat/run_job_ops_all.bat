@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"

set "BACKEND_BAT=%PROJECT_ROOT%\scripts\bat\run_job_ops_backend.bat"
set "FRONTEND_BAT=%PROJECT_ROOT%\scripts\bat\run_job_ops_frontend.bat"

set "BACKEND_TITLE=JobOps_Backend_Dev"
set "FRONTEND_TITLE=JobOps_Frontend_Dev"

set "ACTION=%~1"
set "TARGET=%~2"

if "%ACTION%"=="" set "ACTION=restart"
if "%TARGET%"=="" set "TARGET=all"

if /I not "%ACTION%"=="start" if /I not "%ACTION%"=="stop" if /I not "%ACTION%"=="restart" goto :usage
if /I not "%TARGET%"=="backend" if /I not "%TARGET%"=="frontend" if /I not "%TARGET%"=="all" goto :usage

if not exist "%BACKEND_BAT%" (
  echo [ERROR] File not found: "%BACKEND_BAT%"
  exit /b 1
)

if not exist "%FRONTEND_BAT%" (
  echo [ERROR] File not found: "%FRONTEND_BAT%"
  exit /b 1
)

if /I "%ACTION%"=="stop" goto :do_stop
if /I "%ACTION%"=="start" goto :do_start
if /I "%ACTION%"=="restart" goto :do_restart
goto :usage

:do_restart
call :stop_target "%TARGET%"
timeout /t 1 /nobreak >nul
call :start_target "%TARGET%"
goto :done

:do_stop
call :stop_target "%TARGET%"
goto :done

:do_start
call :start_target "%TARGET%"
goto :done

:stop_target
set "STOP_TARGET=%~1"
echo Stopping Job Ops target: %STOP_TARGET%
if /I "%STOP_TARGET%"=="backend" (
  call :stop_backend
  goto :eof
)
if /I "%STOP_TARGET%"=="frontend" (
  call :stop_frontend
  goto :eof
)
call :stop_backend
call :stop_frontend
goto :eof

:start_target
set "START_TARGET=%~1"
echo Starting Job Ops target: %START_TARGET%
if /I "%START_TARGET%"=="backend" (
  call :start_backend
  goto :eof
)
if /I "%START_TARGET%"=="frontend" (
  call :start_frontend
  goto :eof
)
call :start_backend
timeout /t 2 /nobreak >nul
call :start_frontend
goto :eof

:stop_backend
echo [INFO] Closing backend terminal window...
taskkill /F /T /FI "WINDOWTITLE eq %BACKEND_TITLE%" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq %BACKEND_TITLE%*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps-Backend" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps-Backend*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps_Backend_Dev" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps_Backend_Dev*" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$regex = '\\\\scripts\\\\bat\\\\run_job_ops_backend\\.bat|JobOps_Backend_Dev|--port 8102'; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $regex } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }" >nul 2>&1
echo [INFO] Releasing backend port 8102...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8102 .*LISTENING"') do (
  taskkill /F /T /PID %%P >nul 2>&1
)
goto :eof

:stop_frontend
echo [INFO] Closing frontend terminal window...
taskkill /F /T /FI "WINDOWTITLE eq %FRONTEND_TITLE%" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq %FRONTEND_TITLE%*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps-Frontend" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps-Frontend*" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps_Frontend_Dev" >nul 2>&1
taskkill /F /T /FI "WINDOWTITLE eq JobOps_Frontend_Dev*" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command "$regex = '\\\\scripts\\\\bat\\\\run_job_ops_frontend\\.bat|JobOps_Frontend_Dev|--port 5182'; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $regex } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }" >nul 2>&1
echo [INFO] Releasing frontend port 5182...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5182 .*LISTENING"') do (
  taskkill /F /T /PID %%P >nul 2>&1
)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5183 .*LISTENING"') do (
  taskkill /F /T /PID %%P >nul 2>&1
)
goto :eof

:start_backend
echo [INFO] Opening backend terminal window...
start "%BACKEND_TITLE%" /min cmd /k "title %BACKEND_TITLE% && cd /d "%PROJECT_ROOT%" && call "%BACKEND_BAT%""
goto :eof

:start_frontend
echo [INFO] Opening frontend terminal window...
start "%FRONTEND_TITLE%" /min cmd /k "title %FRONTEND_TITLE% && cd /d "%PROJECT_ROOT%" && call "%FRONTEND_BAT%""
goto :eof

:usage
echo Usage:
echo   run_job_ops_all.bat [start^|stop^|restart] [backend^|frontend^|all]
echo.
echo Examples:
echo   run_job_ops_all.bat
echo   run_job_ops_all.bat restart all
echo   run_job_ops_all.bat stop backend
echo   run_job_ops_all.bat start frontend
exit /b 1

:done
echo.
echo Done.
if /I "%ACTION%"=="start" if /I "%TARGET%"=="all" (
  echo - Backend:  http://127.0.0.1:8102
  echo - Frontend: http://127.0.0.1:5182
)
if /I "%ACTION%"=="restart" if /I "%TARGET%"=="all" (
  echo - Backend:  http://127.0.0.1:8102
  echo - Frontend: http://127.0.0.1:5182
)
exit /b 0
