@echo off
setlocal
cd /d "%~dp0"
set KO2_DAW_GUI_MODE=stable
call "%~dp0launch_ko2_daw.cmd" %*
exit /b %errorlevel%
