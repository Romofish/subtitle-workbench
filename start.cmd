@echo off
call "%~dp0workbench.cmd" start %*
exit /b %ERRORLEVEL%
