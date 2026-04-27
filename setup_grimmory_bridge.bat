@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -m pip install -r "%SCRIPT_DIR%requirements.txt"
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python -m pip install -r "%SCRIPT_DIR%requirements.txt"
  exit /b %errorlevel%
)

echo Could not find Python. Please install Python 3 and try again.
exit /b 1
