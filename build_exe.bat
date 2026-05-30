@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating local virtual environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -e . pyinstaller
if errorlevel 1 goto :error

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
".venv\Scripts\python.exe" -m PyInstaller packaging\ko2_daw.spec --clean --noconfirm
if errorlevel 1 goto :error

echo.
echo Built executable folder:
echo   dist\KO2-DAW\KO2-DAW.exe
echo.
pause
exit /b 0

:error
echo.
echo Build failed. Check the messages above.
pause
exit /b 1
