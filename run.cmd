@echo off
cd /d "%~dp0"

REM Prefer py (Python Launcher), then python
set PY=
where py >nul 2>&1
if %errorlevel% equ 0 (
  set PY=py
  set PYW=py
)
if "%PY%"=="" (
  where python >nul 2>&1
  if %errorlevel% equ 0 (
    set PY=python
    set PYW=pythonw
  )
)
if "%PY%"=="" (
  echo Python was not found.
  echo.
  echo Turn ON the "py.exe" alias:
  echo   Settings - Apps - Advanced app settings - App execution aliases
  echo   Find "Python install manager" - py.exe - turn it ON.
  echo.
  echo Or install Python from https://www.python.org/downloads/
  echo and check "Add Python to PATH".
  pause
  exit /b 1
)

if "%~1"=="" (
  start "" %PY% swooshhh.py --gui
  exit /b 0
)
if /i "%~1"=="tray" (
  %PYW% swooshhh.py
  if errorlevel 1 %PY% swooshhh.py
  exit /b 0
)
if /i "%~1"=="gui" (
  %PY% swooshhh.py --gui
  if errorlevel 1 (
    echo Failed to run. Install deps: %PY% -m pip install -r requirements.txt
    pause
  )
  exit /b 0
)
if /i "%~1"=="build" (
  call build_exe.bat
  exit /b 0
)
echo Usage: run.cmd [tray^|gui^|build]
echo   (no args) = start with GUI
echo   tray      = tray only, no window
echo   gui       = same as no args
echo   build     = create swooshhh.exe
pause
