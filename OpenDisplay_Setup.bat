@echo off
title OpenDisplay - Complete 1-Click Setup and Launcher
cd /d "%~dp0"

echo ========================================================
echo          OpenDisplay - USB Extended Monitor Setup        
echo ========================================================
echo.

set ADB="%~dp0app_win\adb.exe"
if not exist %ADB% (
    if exist "%~dp0adb.exe" set ADB="%~dp0adb.exe"
)
where adb >nul 2>nul
if %errorlevel% equ 0 (
    set ADB=adb
)

:: Step 0: Ensure Virtual Extended Screen is Enabled
set DEVCON="%~dp0server\driver\vdd_bin\VirtualDisplayDriver\devcon.exe"
if not exist %DEVCON% (
    if exist "%~dp0devcon.exe" set DEVCON="%~dp0devcon.exe"
)
if exist %DEVCON% (
    %DEVCON% status Root\MttVDD | findstr /i "running" >nul
    if %errorlevel% neq 0 (
        echo [Setup] Enabling Virtual Extended Screen...
        powershell -Command "Start-Process '%DEVCON%' -ArgumentList 'enable Root\MttVDD' -Verb RunAs -WindowStyle Hidden"
        timeout /t 2 >nul
    )
)

:: Step 1: Check ADB Connection
echo [Step 1/4] Checking connected Android devices...
%ADB% devices
echo.

:: Step 2: Install APK onto device if connected
echo [Step 2/4] Installing OpenDisplay.apk onto tablet...
%ADB% install -r -d "OpenDisplay.apk"
if %errorlevel% equ 0 (
    echo SUCCESS: OpenDisplay.apk installed on tablet!
) else (
    echo NOTE: Device not ready for install or not connected yet.
)
echo.

:: Step 3: Setup USB Reverse Tunnel (tablet connects to Windows host)
echo [Step 3/4] Establishing USB High-Speed Tunnel...
%ADB% forward --remove-all >nul 2>nul
%ADB% reverse tcp:7070 tcp:7070
%ADB% reverse tcp:8080 tcp:8080
echo Tunnel active (tcp:7070 native app, tcp:8080 web viewer).
echo.

:: Step 4: Launching
echo [Step 4/4] Launching OpenDisplay on tablet and starting PC streamer...
%ADB% shell am start -n com.display.usbclient/.MainActivity

echo.
echo ========================================================
echo Starting OpenDisplay Windows Host Streamer...
echo ========================================================
if exist "dist\OpenDisplay\OpenDisplay.exe" (
    start "" "dist\OpenDisplay\OpenDisplay.exe"
) else if exist "OpenDisplay.exe" (
    start "" "OpenDisplay.exe"
) else (
    start "" python opendisplay_server.py
)
echo [Success] OpenDisplay is running silently in the Windows System Tray!
timeout /t 2 >nul
exit
