@echo off
title OpenDisplay - Install AOAP WinUSB Driver
cd /d "%~dp0"

echo Installing OpenDisplay AOAP Driver...
pnputil.exe /add-driver "server\driver\aoap_bin\opendisplay_aoap.inf" /install
if %errorlevel% neq 0 (
    echo Attempting installation via devcon...
    server\driver\vdd_bin\VirtualDisplayDriver\devcon.exe dp_add "server\driver\aoap_bin\opendisplay_aoap.inf"
)
echo Driver installation complete.
