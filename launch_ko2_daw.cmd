@echo off
setlocal
cd /d "%~dp0"
python run_ko2_daw.py %*
echo.
pause
