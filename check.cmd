@echo off
call "%~dp0workbench.cmd" check %*
exit /b %ERRORLEVEL%
