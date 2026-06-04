@echo off
setlocal
cd /d "%~dp0"
set KO2_DAW_GUI_MODE=stable

if not exist ".venv\Scripts\python.exe" (
  echo Creating local virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

echo Installing/updating KO II DAW package...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :error

echo Launching KO II DAW in stable mode...
".venv\Scripts\python.exe" -m ko2_daw
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo KO II DAW stable launch failed. Check the messages above.
pause
exit /b 1
