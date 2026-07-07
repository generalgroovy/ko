@echo off
setlocal
cd /d "%~dp0"
set "BOOTSTRAP=py -3"
where py >nul 2>&1
if errorlevel 1 set "BOOTSTRAP=python"

%BOOTSTRAP% -c "import pytest; import ko2_daw" >nul 2>&1
if errorlevel 1 goto :error
%BOOTSTRAP% -m pytest -q
if errorlevel 1 goto :error
exit /b 0

:error
echo KO II DAW tests failed.
pause
exit /b 1
