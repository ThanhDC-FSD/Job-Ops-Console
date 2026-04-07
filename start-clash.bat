@echo off
REM Ensure Clash Meta uses the curated config directory with WARP-driven routing.
if not exist "%~dp0config\clash-meta.yaml" (
  echo Missing config/clash-meta.yaml
  exit /b 1
)
cd /d "%~dp0"
start "" "%~dp0clash-meta.exe" -d "%~dp0config" -f "%~dp0config\clash-meta.yaml"
