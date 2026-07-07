@echo off
setlocal
cd /d "%~dp0"

set "BOOTSTRAP=py -3"
where py >nul 2>&1
if errorlevel 1 set "BOOTSTRAP=python"

%BOOTSTRAP% -c "import tkinter; import ko2_daw" >nul 2>&1
if errorlevel 1 goto :error

%BOOTSTRAP% -m ko2_daw %*
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo KO II DAW could not start.
echo Install Python 3.11 or newer with Tcl/Tk, then run this launcher again.
pause
exit /b 1
