@echo off
setlocal
cd /d "%~dp0"
call "%~dp0launch_ko2_daw.cmd" %*
exit /b %errorlevel%
