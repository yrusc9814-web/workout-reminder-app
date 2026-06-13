@echo off
setlocal
set "APP_DIR=%~dp0.."
cd /d "%APP_DIR%"

set "URL=http://127.0.0.1:3000"
set "HOST=127.0.0.1"
set "PORT=3000"

python -c "import socket; socket.create_connection(('127.0.0.1', 3000), 1).close()" >nul 2>nul
if errorlevel 1 (
  start "运动提醒 App 后端" /min python -m uvicorn main:app --host %HOST% --port %PORT%
  timeout /t 5 /nobreak >nul
)

start "" "%URL%"
exit /b 0
