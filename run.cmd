@echo off
cd /d "%~dp0"

set PY=
where py >nul 2>&1 && set PY=py
if "%PY%"=="" where python >nul 2>&1 && set PY=python
if "%PY%"=="" (
  echo Python not found. Enable "py.exe" in App execution aliases or add Python to PATH.
  echo https://www.python.org/downloads/
  pause
  exit /b 1
)

if "%~1"=="" (
  start "" %PY% swooshhh.py --gui
  exit /b 0
)
if /i "%~1"=="gui" (
  %PY% swooshhh.py --gui
  if errorlevel 1 echo Install deps: run.cmd install
  exit /b 0
)
if /i "%~1"=="tray" (
  %PY% swooshhh.py
  exit /b 0
)
if /i "%~1"=="install" (
  %PY% -m pip install -r requirements.txt
  echo Run: run.cmd  or  run.cmd gui
  pause
  exit /b 0
)
if /i "%~1"=="build" (
  %PY% -m pip install pyinstaller --quiet
  %PY% make_icon.py
  if not exist swooshhh.ico (echo swooshhh.ico not created. & exit /b 1)
  %PY% -m PyInstaller --onefile --windowed --clean --icon=swooshhh.ico --name swooshhh swooshhh.py
  if exist "dist\swooshhh.exe" (echo Built: dist\swooshhh.exe) else (echo Build failed. & exit /b 1)
  pause
  exit /b 0
)

echo Usage: run.cmd [gui^|tray^|install^|build]
echo   (no args) = start with GUI
echo   gui       = run with GUI
echo   tray      = tray only
echo   install   = pip install -r requirements.txt
echo   build     = create dist\swooshhh.exe
pause
