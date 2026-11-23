@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo  Emi isn't set up yet - double-click setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py --check
pause
