@echo off
call "%~dp0workbench.cmd" setup %*
exit /b %ERRORLEVEL%
