@echo off
REM Build swooshhh.exe with PyInstaller
set SCRIPT=swooshhh.py
set EXE=swooshhh
if not exist "%SCRIPT%" (
  echo %SCRIPT% not found. Run from the project folder.
  exit /b 1
)
pip install pyinstaller --quiet
if exist dist rmdir /s /q dist
if exist swooshhh_logo.png (
  py make_ico.py
  if exist swooshhh.ico (
    pyinstaller --onefile --windowed --name "%EXE%" "%SCRIPT%" --icon swooshhh.ico
  ) else (
    echo make_ico.py failed - building without custom icon
    pyinstaller --onefile --windowed --name "%EXE%" "%SCRIPT%"
  )
) else (
  echo swooshhh_logo.png not found - building without logo
  pyinstaller --onefile --windowed --name "%EXE%" "%SCRIPT%"
)
if exist "dist\%EXE%.exe" (
  echo.
  echo Built: dist\%EXE%.exe
  echo Run it or attach dist\%EXE%.exe to a GitHub Release.
) else (
  echo Build failed.
  exit /b 1
)
