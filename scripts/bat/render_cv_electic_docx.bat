@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "TARGET=%PROJECT_ROOT%\scripts\python\render_cv_docx.py"
set "PYTHONPATH="
set "PYTHONHOME="
set /p OUTPUT_NAME=Enter output file name (without extension, default: full_doc_stlye_electric): 
if "%OUTPUT_NAME%"=="" set "OUTPUT_NAME=full_doc_stlye_electric"
set "OUTPUT_DOCX=documents\%OUTPUT_NAME%.docx"
set "OUTPUT_PDF=documents\%OUTPUT_NAME%.pdf"

if not exist "%VENV_PY%" (
  echo [ERROR] Virtual environment not found at "%PROJECT_ROOT%\.venv"
  echo Please run: python -m venv .venv
  exit /b 1
)
if not exist "%TARGET%" (
  echo [ERROR] File not found: "%TARGET%"
  exit /b 1
)

pushd "%PROJECT_ROOT%"
"%VENV_PY%" "%TARGET%" -i "input\full_doc_stlye_electric.txt" -o "%OUTPUT_DOCX%" --pdf-output "%OUTPUT_PDF%"
set "EXIT_CODE=%ERRORLEVEL%"
popd

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Script exited with error code %EXIT_CODE%.
)
endlocal
exit /b %EXIT_CODE%
