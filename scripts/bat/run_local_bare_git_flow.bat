@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "WORKSPACE=%%~fI"
set "DEPLOY_ROOT=D:\3.bat_file_automate\6.Job_op_console_deployment"
set "PUBLISH_BAT=%DEPLOY_ROOT%\run_publish_job_ops_to_bare.bat"
set "CD_ONCE_BAT=%DEPLOY_ROOT%\run_job_ops_cd_once.bat"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=dev"
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format \"yyyyMMdd_HHmmss\""' ) do set "RUN_ID=%%T"
set "LOG_COMPONENT=CICD.LocalGitFlow"

if not exist "%WORKSPACE%\.git" (
  call :log ERROR error "Workspace git repo not found: %WORKSPACE%"
  exit /b 1
)

if not exist "%PUBLISH_BAT%" (
  call :log ERROR error "Publish launcher not found: %PUBLISH_BAT%"
  exit /b 1
)

call :ensure_clean
if errorlevel 1 exit /b 1

if /I "%ACTION%"=="dev" goto :dev
if /I "%ACTION%"=="release" goto :release
goto :usage

:ensure_clean
pushd "%WORKSPACE%" >nul
set "STATUS_FILE=%TEMP%\job_ops_git_status_%RANDOM%_%RANDOM%.txt"
git status --short > "%STATUS_FILE%"
for /f %%L in ('type "%STATUS_FILE%"') do (
  goto :dirty
)
del "%STATUS_FILE%" >nul 2>&1
popd >nul
goto :eof

:dirty
call :log ERROR error "Workspace has uncommitted changes. Commit or stash them first."
type "%STATUS_FILE%"
del "%STATUS_FILE%" >nul 2>&1
popd >nul
exit /b 1

:dev
call :log INFO note "Switching workspace to development branch..."
pushd "%WORKSPACE%" >nul
git show-ref --verify --quiet refs/heads/development
if errorlevel 1 (
  call :log INFO note "Local branch development does not exist yet. Creating it from current HEAD..."
  git checkout -b development
) else (
  git checkout development
)
if errorlevel 1 (
  popd >nul
  call :log ERROR error "Failed to switch to development."
  exit /b 1
)
for /f "delims=" %%B in ('git branch --show-current') do set "CURRENT_BRANCH=%%B"
popd >nul
call :log INFO note "Ready to develop on branch: %CURRENT_BRANCH%"
exit /b 0

:release
call :log INFO note "Releasing local code: merge development into main, then publish bare main with deploy marker..."
pushd "%WORKSPACE%" >nul
git show-ref --verify --quiet refs/heads/development
if errorlevel 1 (
  popd >nul
  call :log ERROR error "Local branch development does not exist. Run: %~nx0 dev"
  exit /b 1
)

git checkout development
if errorlevel 1 (
  popd >nul
  call :log ERROR error "Failed to checkout development."
  exit /b 1
)

git show-ref --verify --quiet refs/heads/main
if errorlevel 1 (
  call :log INFO note "Local branch main does not exist yet. Creating it from development..."
  git checkout -b main
  if errorlevel 1 (
    popd >nul
    call :log ERROR error "Failed to create main from development."
    exit /b 1
  )
) else (
  git checkout main
  if errorlevel 1 (
    popd >nul
    call :log ERROR error "Failed to checkout main."
    exit /b 1
  )
)

git merge --no-ff development -m "Merge branch 'development' into main"
if errorlevel 1 (
  popd >nul
  call :log ERROR error "Merge failed. Resolve conflicts, commit, then rerun."
  exit /b 1
)
popd >nul

call "%PUBLISH_BAT%" -Deploy
if errorlevel 1 (
  call :log ERROR error "Publish to bare local main failed."
  exit /b 1
)

if exist "%CD_ONCE_BAT%" (
  call :log INFO note "Triggering one immediate CD sync so the release deploys now..."
  call "%CD_ONCE_BAT%"
  if errorlevel 1 (
    call :log ERROR error "Immediate CD sync failed."
    exit /b 1
  )
) else (
  call :log WARN warn "CD one-shot launcher not found, fallback to scheduled task timing: %CD_ONCE_BAT%"
)

pushd "%WORKSPACE%" >nul
git checkout development >nul
popd >nul
call :log INFO note "Release complete. Bare local main has new deploy commit and immediate CD sync has been requested."
exit /b 0

:usage
call :log INFO note "Usage:"
echo   %~nx0 dev
echo   %~nx0 release
echo.
call :log INFO note "Commands:"
echo   dev      Switch to local development branch for daily work
echo   release  Merge development into main and publish main to the local bare repo with -Deploy
exit /b 1

:log
set "LEVEL=%~1"
set "EVENT=%~2"
set "MSG=%~3"
for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-ddTHH:mm:ssK\""' ) do set "NOW=%%T"
echo ts=%NOW% level=%LEVEL% component=%LOG_COMPONENT% event=%EVENT% run_id=%RUN_ID% trace_id=- job_id=- message="%MSG%"
exit /b 0


rem .\run_local_bare_git_flow.bat dev
rem .\run_local_bare_git_flow.bat release
