@echo off
cd /d "%~dp0"
echo.
echo  Installing Claude Code - Emi's Claude helper. It runs on your Claude plan (Pro or Max), no API key needed.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where claude >nul 2>nul
if errorlevel 1 (
  echo.
  echo  The install didn't finish. See https://code.claude.com/docs/en/setup and try again.
  pause
  exit /b 1
)
echo.
echo  ============================================================
echo   Now sign in once with your Claude account.
echo   Claude Code opens below and shows a login link / browser window.
echo   After you're signed in and see its prompt, type  /exit  and press Enter.
echo  ============================================================
echo.
claude
echo.
echo  Done! Restart Emi, open her menu and make sure "Claude helper" is on.
echo  Tip: run check.bat to confirm Emi can reach Claude.
pause
