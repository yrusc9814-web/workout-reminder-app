@echo off
setlocal
cd /d "%~dp0.."
python scripts\windows_daily_reminder.py %*
exit /b %ERRORLEVEL%
