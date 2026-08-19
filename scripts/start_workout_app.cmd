@echo off
setlocal
set "APP_DIR=%~dp0.."
cd /d "%APP_DIR%"

set "URL=http://127.0.0.1:3000"
set "HOST=127.0.0.1"
set "PORT=3000"
set "LOG_DIR=%APP_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\start_workout_app.log"
set "SERVER_CMD=%LOG_DIR%\start_workout_app_server.cmd"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo [%DATE% %TIME%] Starting workout app launcher > "%LOG_FILE%"
echo [%DATE% %TIME%] App dir: %APP_DIR% >> "%LOG_FILE%"

python -c "import socket; socket.create_connection(('127.0.0.1', 3000), 1).close()" >nul 2>nul
if errorlevel 1 (
  echo [%DATE% %TIME%] Port %PORT% is not listening; starting uvicorn. >> "%LOG_FILE%"
  > "%SERVER_CMD%" echo @echo off
  >> "%SERVER_CMD%" echo cd /d "%APP_DIR%"
  >> "%SERVER_CMD%" echo python -m uvicorn main:app --host %HOST% --port %PORT% ^>^> "%LOG_FILE%" 2^>^&1
  start "运动提醒 App 后端" /min "%ComSpec%" /d /c call "%SERVER_CMD%"
) else (
  echo [%DATE% %TIME%] Port %PORT% is already listening. >> "%LOG_FILE%"
)

for /l %%I in (1,1,15) do (
  python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/health', timeout=1)); raise SystemExit(0 if data.get('status') == 'ok' else 1)" >nul 2>nul
  if not errorlevel 1 goto healthy
  "%SystemRoot%\System32\ping.exe" -n 2 127.0.0.1 >nul
)

echo [%DATE% %TIME%] ERROR: health check failed for %URL%/api/health. See "%LOG_FILE%". >> "%LOG_FILE%"
echo Failed to start Workout Reminder App. See log: "%LOG_FILE%"
exit /b 1

:healthy
echo [%DATE% %TIME%] Health check passed. Opening %URL%. >> "%LOG_FILE%"
start "" "%URL%"
exit /b 0
