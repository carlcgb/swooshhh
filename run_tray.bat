@echo off
REM Launch Swooshhh (tray only, no GUI window)
cd /d "%~dp0"
pythonw swooshhh.py 2>nul
if errorlevel 1 (
  py swooshhh.py 2>nul || python swooshhh.py
)
