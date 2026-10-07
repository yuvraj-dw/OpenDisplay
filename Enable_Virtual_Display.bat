@echo off
title Enable OpenDisplay Virtual Screen
cd /d "%~dp0"
set DEVCON=%~dp0server\driver\vdd_bin\VirtualDisplayDriver\devcon.exe

echo Enabling Virtual Display...
powershell -Command "Start-Process '%DEVCON%' -ArgumentList 'enable Root\MttVDD' -Verb RunAs -WindowStyle Hidden"
echo.
echo Virtual display enabled! Windows now detects your secondary screen.
timeout /t 3 >nul
