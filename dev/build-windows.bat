@echo off
REM Builds "My Data Center.exe" (run on a Windows PC). Output: dist\My Data Center\
cd /d "%~dp0\.."
py -3 -m venv .buildenv || python -m venv .buildenv
.buildenv\Scripts\python -m pip install -q --upgrade pip
.buildenv\Scripts\python -m pip install -q -r requirements.txt pyinstaller
.buildenv\Scripts\pyinstaller --noconfirm --clean --windowed --name "My Data Center" ^
  --icon assets\icon.ico --add-data "ui.html;." mydatacenter.py
echo.
echo Done: dist\My Data Center\My Data Center.exe
pause
