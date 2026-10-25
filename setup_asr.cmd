@echo off
call "%~dp0workbench.cmd" setup-asr %*
exit /b %ERRORLEVEL%
