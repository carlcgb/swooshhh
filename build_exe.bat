@echo off
REM Build swooshhh.exe with PyInstaller
set SCRIPT=swooshhh.py
set EXE=swooshhh
if not exist "%SCRIPT%" (
  echo %SCRIPT% not found. Run from the project folder.
  exit /b 1
)
pip install pyinstaller --quiet
if exist swooshhh_logo.png (
  py -c "from PIL import Image; i=Image.open('swooshhh_logo.png').convert('RGBA'); i.save('swooshhh.ico', format='ICO', sizes=[(256,256),(48,48),(32,32),(16,16)])" 2>nul
  if exist swooshhh.ico (
    pyinstaller --onefile --windowed --name "%EXE%" "%SCRIPT%" --add-data "swooshhh_logo.png;." --icon swooshhh.ico
  ) else (
    pyinstaller --onefile --windowed --name "%EXE%" "%SCRIPT%" --add-data "swooshhh_logo.png;."
  )
) else (
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
