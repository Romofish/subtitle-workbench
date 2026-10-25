@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0youtube_download.ps1" %*
set "DOWNLOAD_RESULT=%ERRORLEVEL%"
if not "%DOWNLOAD_RESULT%"=="0" if not defined WORKBENCH_NO_PAUSE pause
exit /b %DOWNLOAD_RESULT%
