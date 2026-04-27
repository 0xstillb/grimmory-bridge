@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"

set "SCRIPT_DIR=%~dp0"
set "SCRIPT_PATH=%SCRIPT_DIR%opf_to_embedded_metadata.py"
set "BUNDLED_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "BUNDLED_PYW=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"

if "%~1"=="/?" goto :help
if /i "%~1"=="-h" goto :help
if /i "%~1"=="--help" goto :help
if "%~1"=="" goto :launch_gui
if /i "%~1"=="--gui" goto :launch_gui

goto :launch_cli

:launch_gui
if exist "%BUNDLED_PYW%" (
  start "" "%BUNDLED_PYW%" "%SCRIPT_PATH%" --gui
  exit /b 0
)

if exist "%BUNDLED_PY%" (
  start "" "%BUNDLED_PY%" "%SCRIPT_PATH%" --gui
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  start "" py "%SCRIPT_PATH%" --gui
  exit /b 0
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw "%SCRIPT_PATH%" --gui
  exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
  start "" python "%SCRIPT_PATH%" --gui
  exit /b 0
)

echo Could not find a usable Python runtime for GUI mode.
echo Tried:
echo   1. Codex bundled pythonw
echo   2. Codex bundled python
echo   3. py
echo   4. pythonw
echo   5. python
exit /b 1

:launch_cli

if exist "%BUNDLED_PY%" (
  "%BUNDLED_PY%" "%SCRIPT_PATH%" %*
  exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
  py "%SCRIPT_PATH%" %*
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "%SCRIPT_PATH%" %*
  exit /b %errorlevel%
)

echo Could not find a usable Python runtime for Grimmory Bridge.
echo Tried:
echo   1. Codex bundled Python
echo   2. py
echo   3. python
exit /b 1

:help
echo Grimmory Bridge
echo OPF to Embedded and JSON
echo.
echo Usage:
echo   opf_to_embedded_metadata.bat
echo   opf_to_embedded_metadata.bat --root "D:\Books" --write
echo   opf_to_embedded_metadata.bat --inspect "D:\Books\Novel\Book.epub"
echo   opf_to_embedded_metadata.bat --gui
echo.
echo With no arguments, the GUI opens automatically.
exit /b 0
