@echo off
setlocal
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Please right-click this file and select "Run as administrator".
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Light Retouch HRMS LAN TCP 8000"
echo Firewall rule removed.
pause
