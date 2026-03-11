@echo off
REM Build swooshhh.exe with PyInstaller
set SCRIPT=swooshhh.py
set EXE=swooshhh
if not exist "%SCRIPT%" (
  echo %SCRIPT% not found. Run from the project folder.
  exit /b 1
)
pip install pyinstaller --quiet
pyinstaller --onefile --windowed --name "%EXE%" "%SCRIPT%"
if exist "dist\%EXE%.exe" (
  echo.
  echo Built: dist\%EXE%.exe
  echo Run it or attach dist\%EXE%.exe to a GitHub Release.
) else (
  echo Build failed.
  exit /b 1
)
