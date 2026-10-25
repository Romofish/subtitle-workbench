@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if /i "%~1"=="download" goto download
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "WB_PYTHON="
if defined WORKBENCH_PYTHON if exist "%WORKBENCH_PYTHON%" set "WB_PYTHON=%WORKBENCH_PYTHON%"
if not defined WB_PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "WB_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined WB_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "WB_PYTHON=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined WB_PYTHON if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "WB_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined WB_PYTHON (
  echo Python 3.13 is required. Install it or set WORKBENCH_PYTHON to its full path.
  if not defined WORKBENCH_NO_PAUSE pause
  exit /b 1
)
"%WB_PYTHON%" -X utf8 "%~dp0scripts\windows_entry.py" %*
set "WB_RESULT=%ERRORLEVEL%"
if not "%WB_RESULT%"=="0" if not defined WORKBENCH_NO_PAUSE pause
exit /b %WB_RESULT%

:download
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0workbench.ps1" %*
exit /b %ERRORLEVEL%
