@echo off
setlocal
net session >nul 2>&1
if not "%errorlevel%"=="0" (
  echo Please right-click this file and select "Run as administrator".
  pause
  exit /b 1
)

netsh advfirewall firewall delete rule name="Light Retouch HRMS LAN TCP 8000" >nul 2>&1
netsh advfirewall firewall add rule name="Light Retouch HRMS LAN TCP 8000" dir=in action=allow protocol=TCP localport=8000 profile=private
if errorlevel 1 (
  echo Could not add the firewall rule.
  pause
  exit /b 1
)
echo Firewall rule added for TCP port 8000 on Private networks.
echo Only use this on your trusted office LAN.
pause
