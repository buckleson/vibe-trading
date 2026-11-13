@echo off
setlocal
cd /d "%~dp0"
title Buckleson

set "UV=%~dp0tools\uv.exe"
if not exist "%UV%" set "UV=uv"

echo.
echo   Buckleson - trading desk with a built-in Claude agent
echo   Starting on http://127.0.0.1:5000  (first start installs Python and dependencies)
echo   Close this window to stop.
echo.

rem Open the desk in the browser once the server has had time to start.
start "" /b cmd /c "timeout /t 20 /nobreak >nul & start http://127.0.0.1:5000/dashboard"

"%UV%" run --python 3.12 app.py
echo.
echo Buckleson stopped.
pause
