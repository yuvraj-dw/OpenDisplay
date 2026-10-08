@echo off
title OpenDisplay - USB Extended Display
cd /d "%~dp0"

:: Use bundled ADB if not in path
set ADB=app_win\adb.exe
where adb >nul 2>nul
if %errorlevel% equ 0 (
    set ADB=adb
)

%ADB% reverse tcp:7070 tcp:7070 >nul 2>nul
%ADB% reverse tcp:8080 tcp:8080 >nul 2>nul
%ADB% shell am start -n com.display.usbclient/.MainActivity >nul 2>nul

if exist "dist\OpenDisplay\OpenDisplay.exe" (
    start "" "dist\OpenDisplay\OpenDisplay.exe"
) else if exist "OpenDisplay.exe" (
    start "" "OpenDisplay.exe"
) else (
    start "" pythonw opendisplay_server.py
)

exit
