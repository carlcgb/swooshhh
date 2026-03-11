@echo off
REM Install dependencies for Swooshhh
cd /d "%~dp0"
echo Checking for Python...
py -m pip --version >nul 2>&1
if errorlevel 1 (
  python -m pip --version >nul 2>&1
  if errorlevel 1 (
    echo Python not found. Install Python from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
  )
  python -m pip install -r requirements.txt
) else (
  py -m pip install -r requirements.txt
)
echo.
echo Done. Run: run.cmd  or  py swooshhh.py --gui
pause
