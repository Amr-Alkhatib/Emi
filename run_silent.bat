@echo off
rem Starts Emi without a console window.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo  Emi isn't set up yet - double-click setup.bat first.
  pause
  exit /b 1
)
start "" .venv\Scripts\pythonw.exe main.py
