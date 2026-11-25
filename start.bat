@echo off
setlocal
cd /d "%~dp0"
set HRMS_HOST=0.0.0.0
set HRMS_PORT=8000

echo ======================================================
echo       LIGHT RETOUCH MANAGEMENT SYSTEM V4 - OFFICE LAN SERVER
echo ======================================================
echo This PC:   http://127.0.0.1:8000
echo Other PCs: http://192.168.0.244:8000
echo.
echo Keep this window open while employees use the system.
echo Press Ctrl+C to stop the server.
echo ======================================================
echo.
python app.py
if errorlevel 1 (
  echo.
  echo HRMS could not start. Check that Python is installed and port 8000 is free.
)
pause
