@echo off
title Disable OpenDisplay Virtual Screen
cd /d "%~dp0"
set DEVCON=%~dp0server\driver\vdd_bin\VirtualDisplayDriver\devcon.exe

echo Disabling Virtual Display...
powershell -Command "Start-Process '%DEVCON%' -ArgumentList 'disable Root\MttVDD' -Verb RunAs -WindowStyle Hidden"
echo.
echo Virtual display disabled! Windows is now back to a single screen.
timeout /t 3 >nul
