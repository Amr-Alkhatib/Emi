@echo off
setlocal
cd /d "%~dp0"
if not exist data mkdir data
set "LOG=%~dp0data\setup.log"
echo Emi setup %date% %time% > "%LOG%"
echo.
echo  Setting up Emi...  (the first time takes a few minutes)
echo.

rem ---- 1. find a good Python: 3.13 / 3.12 / 3.11 preferred (3.14 is very new, some voice/UI packages lag) ----
set "PYEXE="
for %%V in (313 312 311) do (
  if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set PYEXE="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)
for %%V in (3.13 3.12 3.11) do (
  if not defined PYEXE (
    py -%%V -c "import sys" <nul >nul 2>nul && set "PYEXE=py -%%V"
  )
)
if not defined PYEXE (
  python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" <nul >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo  Python wasn't found. Install Python 3.13 from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH". Then run setup.bat again.
  echo NO PYTHON FOUND >> "%LOG%"
  pause
  exit /b 1
)
echo  Using Python: %PYEXE%
echo Using Python: %PYEXE% >> "%LOG%"
%PYEXE% --version >> "%LOG%" 2>&1
%PYEXE% -c "import sys; sys.exit(1 if sys.version_info[:2] >= (3, 14) else 0)" <nul >nul 2>nul || echo  Note: this is Python 3.14+. If installing fails, install Python 3.13 from python.org and run setup again.

rem ---- 2. private environment (.venv) ----
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys" >nul 2>nul || rmdir /s /q .venv
)
if not exist .venv\Scripts\python.exe (
  echo  Creating Emi's private Python environment...
  %PYEXE% -m venv .venv >> "%LOG%" 2>&1
)
if not exist .venv\Scripts\python.exe (
  echo.
  echo  Couldn't create the environment. Details are in data\setup.log
  powershell -NoProfile -Command "Get-Content -Tail 15 '%LOG%'"
  pause
  exit /b 1
)

rem ---- 3. packages ----
echo  Installing packages (details go to data\setup.log)...
.venv\Scripts\python.exe -m pip install --upgrade pip >> "%LOG%" 2>&1
.venv\Scripts\python.exe -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo  Some packages failed to install. The end of the log:
  echo  ------------------------------------------------------------
  powershell -NoProfile -Command "Get-Content -Tail 25 '%LOG%'"
  echo  ------------------------------------------------------------
  echo  Send data\setup.log to Claude, or install Python 3.13 and run setup.bat again.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import webview, faster_whisper, sounddevice, soundfile, edge_tts, openai, yaml, keyboard; print('all packages OK')" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo  Packages installed, but a quick import test failed - see data\setup.log
) else (
  echo  Packages installed.
)

rem ---- 4. API key ----
if not exist .env copy .env.example .env >nul
findstr /r /c:"^GEMINI_API_KEY=..*" .env >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Notepad is opening .env - paste your Gemini API key right after GEMINI_API_KEY= then SAVE and close Notepad.
  start /wait notepad.exe .env
)

rem ---- 5. shortcuts ----
call install_shortcuts.bat
echo SETUP FINISHED >> "%LOG%"
echo.
echo  ============================================================
echo   Done! Next:
echo    1. Optional: double-click install_claude_helper.bat so Emi can hand big jobs to Claude
echo    2. Double-click check.bat to test the key, mic and voice
echo    3. Press your summon shortcut (or double-click run.bat) to start Emi
echo  ============================================================
echo.
pause
