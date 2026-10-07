@echo off
:: BatchGotAdmin
:-------------------------------------
REM --> Check for permissions
IF "%PROCESSOR_ARCHITECTURE%" EQU "amd64" (
>nul 2>&1 "%SYSTEMROOT%\SysWOW64\cacls.exe" "%SYSTEMROOT%\SysWOW64\config\system"
) ELSE (
>nul 2>&1 "%SYSTEMROOT%\system32\cacls.exe" "%SYSTEMROOT%\system32\config\system"
)

REM --> If error flag set, we do not have admin.
if '%errorlevel%' NEQ '0' (
    echo Requesting administrative privileges...
    goto UACPrompt
) else ( goto gotAdmin )

:UACPrompt
    echo Set UAC = CreateObject^("Shell.Application"^) > "%temp%\getadmin.vbs"
    set params = %*:"=""
    echo UAC.ShellExecute "cmd.exe", "/c ""%~s0"" %params%", "", "runas", 1 >> "%temp%\getadmin.vbs"

    "%temp%\getadmin.vbs"
    del "%temp%\getadmin.vbs"
    exit /B

:gotAdmin
    pushd "%CD%"
    CD /D "%~dp0"
:--------------------------------------

echo ========================================================
echo Installing OpenDisplay Virtual Extended Display Driver
echo ========================================================

set DRIVER_DIR=%~dp0server\driver\vdd_bin\VirtualDisplayDriver
set CERT=%DRIVER_DIR%\Virtual_Display_Driver.cer
set INF=%DRIVER_DIR%\MttVDD.inf

echo 1. Adding driver certificate to Trusted Stores...
certutil -addstore -f root "%CERT%"
certutil -addstore -f TrustedPublisher "%CERT%"

echo 2. Installing IddCx Virtual Display Driver Device...
pnputil /add-driver "%INF%" /install
"%DRIVER_DIR%\devcon.exe" install "%INF%" Root\MttVDD

echo 3. Copying vdd_settings.xml to C:\VirtualDisplayDriver...
if not exist "C:\VirtualDisplayDriver" mkdir "C:\VirtualDisplayDriver"
copy /Y "%DRIVER_DIR%\vdd_settings.xml" "C:\VirtualDisplayDriver\vdd_settings.xml"

echo ========================================================
echo Driver Installed! Windows now detects your virtual secondary screen.
echo ========================================================
pause
