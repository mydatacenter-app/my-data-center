@echo off
title My Data Center
cd /d "%~dp0.."
set "VENV=%USERPROFILE%\MyDataCenter\.venv"

if exist "%VENV%\Scripts\pythonw.exe" goto run

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo.
  echo  Python 3 is needed the first time.
  echo  1. Install it from the page that just opened
  echo  2. Tick "Add python.exe to PATH" in the installer
  echo  3. Double-click this file again
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b
)

echo.
echo  First-time setup: installing My Data Center (about a minute)...
echo.
%PY% -m venv "%VENV%" || goto fail
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip -q
"%VENV%\Scripts\python.exe" -m pip install -q -r requirements.txt || goto fail

:run
start "" "%VENV%\Scripts\pythonw.exe" "%~dp0..\mydatacenter.py"
exit /b

:fail
echo.
echo  Setup failed. Check your internet connection and try again.
rmdir /s /q "%VENV%" 2>nul
pause
