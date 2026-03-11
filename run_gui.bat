@echo off
REM Launch Swooshhh with the GUI
cd /d "%~dp0"
py swooshhh.py --gui 2>nul || python swooshhh.py --gui
if errorlevel 1 (
  echo Run from the project folder and ensure dependencies are installed:
  echo   pip install -r requirements.txt
  pause
)
