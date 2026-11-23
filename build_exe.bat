@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo  Run setup.bat first.
  pause
  exit /b 1
)
if not exist data mkdir data
set "LOG=%~dp0data\build.log"
echo.
echo  Building Emi.exe - this takes 5-10 minutes. Details go to data\build.log
echo.
.venv\Scripts\python.exe -m pip install --upgrade pyinstaller > "%LOG%" 2>&1
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name Emi --icon emi.ico ^
  --add-data "emi\web;emi\web" ^
  --collect-all faster_whisper --collect-all ctranslate2 --collect-all onnxruntime ^
  --collect-all webview --collect-all pythonnet --collect-all clr_loader ^
  --collect-all _sounddevice_data --collect-all _soundfile_data ^
  --collect-all edge_tts --collect-data certifi --collect-all ddgs --collect-all primp ^
  --hidden-import pygetwindow --hidden-import pycaw --hidden-import pystray._win32 ^
  main.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo  The build failed. The end of the log:
  powershell -NoProfile -Command "Get-Content -Tail 25 '%LOG%'"
  pause
  exit /b 1
)
for %%F in (config.yaml README.md emi.ico install_shortcuts.bat install_shortcuts.ps1 uninstall_shortcuts.bat uninstall_shortcuts.ps1 install_admin_task.ps1 install_claude_helper.bat) do copy /y "%%F" "dist\Emi\" >nul
if exist .env (copy /y .env "dist\Emi\" >nul) else (copy /y .env.example "dist\Emi\.env" >nul)
if exist models xcopy /e /i /y /q models "dist\Emi\models" >nul
if exist data\state.json (
  if not exist "dist\Emi\data" mkdir "dist\Emi\data"
  copy /y data\state.json "dist\Emi\data\" >nul
)
echo.
echo  ============================================================
echo   Done! Your app is in:  dist\Emi
echo   - Move that whole folder wherever you like (e.g. Documents\Emi)
echo   - Then run install_shortcuts.bat inside it, so the summon shortcut starts Emi.exe
echo   - Windows SmartScreen may warn the first time (the app isn't code-signed):
echo     click "More info" then "Run anyway"
echo  ============================================================
echo.
explorer "dist\Emi"
pause
