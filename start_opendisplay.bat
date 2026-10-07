@echo off
title OpenDisplay - USB Extended Display
cd /d "%~dp0"

echo ========================================================
echo               OpenDisplay USB Engine                    
echo ========================================================

:: Use bundled ADB if not in path
set ADB=app_win\adb.exe
where adb >nul 2>nul
if %errorlevel% equ 0 (
    set ADB=adb
)

echo [1/3] Checking connected Android devices...
%ADB% devices

echo [2/3] Establishing high-speed USB tunnel (tcp:8080)...
%ADB% reverse tcp:8080 tcp:8080

echo [3/3] Starting OpenDisplay screen streamer...
start "" %ADB% shell am start -n com.android.chrome/com.google.android.apps.chrome.Main -d "http://localhost:8080/"

python -u opendisplay_server.py
pause
