<#
.SYNOPSIS
Downloads, unpacks, and prepares the Virtual Display Driver (VDD).

.DESCRIPTION
Downloads the open-source Virtual Display Driver package from GitHub releases,
unpacks it into the local server/driver/vdd_bin folder, and prepares the driver
INF, certificate, and configuration files for installation.
#>
[CmdletBinding()]
param(
    [string]$DownloadUrl = "https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/download/24.10.27/VirtualDisplayDriver-x64.zip",
    [string]$DestinationPath,
    [switch]$Install,
    [switch]$ForceDownload
)

$ErrorActionPreference = "Stop"

try {
    $targetDir = if ($DestinationPath) { $DestinationPath } else { Join-Path $PSScriptRoot "vdd_bin" }
    if (-not (Test-Path -LiteralPath $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    $zipPath = Join-Path $targetDir "VirtualDisplayDriver.zip"

    if (-not (Test-Path -LiteralPath $zipPath) -or $ForceDownload) {
        Write-Host "Downloading Virtual Display Driver from $DownloadUrl..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath -UseBasicParsing
        Write-Host "Download completed: $zipPath"
    } else {
        Write-Host "Using existing archive: $zipPath"
    }

    Write-Host "Unpacking archive to $targetDir..."
    Expand-Archive -Path $zipPath -DestinationPath $targetDir -Force

    $infFile = Get-ChildItem -Path $targetDir -Filter "*.inf" -Recurse | Select-Object -First 1
    $cerFile = Get-ChildItem -Path $targetDir -Filter "*.cer" -Recurse | Select-Object -First 1
    $xmlFile = Get-ChildItem -Path $targetDir -Filter "vdd_settings.xml" -Recurse | Select-Object -First 1

    if (-not $infFile) {
        throw "Could not find driver INF file in $targetDir"
    }

    Write-Host "Driver package ready at: $targetDir"
    Write-Host " - INF: $($infFile.FullName)"
    if ($cerFile) {
        Write-Host " - Certificate: $($cerFile.FullName)"
    }
    if ($xmlFile) {
        Write-Host " - Settings: $($xmlFile.FullName)"
    }

    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($Install) {
        if (-not $isAdmin) {
            Write-Warning "Administrator rights required to install driver. Attempting elevated execution..."
            Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -NoProfile -File `"$PSCommandPath`" -Install" -Wait
            exit 0
        }

        if ($cerFile) {
            Write-Host "Installing certificate to Root and TrustedPublisher stores..."
            certutil -addstore -f root "$($cerFile.FullName)" | Out-Null
            certutil -addstore -f TrustedPublisher "$($cerFile.FullName)" | Out-Null
        }

        Write-Host "Installing driver via pnputil..."
        & pnputil /add-driver "$($infFile.FullName)" /install
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "pnputil returned exit code $LASTEXITCODE"
        } else {
            Write-Host "Driver installed successfully."
        }
    } else {
        Write-Host ""
        Write-Host "VDD package prepared. To install certificate and driver via pnputil (Admin prompt):"
        if ($cerFile) {
            Write-Host "  certutil -addstore -f root `"$($cerFile.FullName)`""
            Write-Host "  certutil -addstore -f TrustedPublisher `"$($cerFile.FullName)`""
        }
        Write-Host "  pnputil /add-driver `"$($infFile.FullName)`" /install"
        Write-Host ""
        Write-Host "Or run with -Install from an elevated terminal:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File server/driver/setup_vdd.ps1 -Install"
    }

    exit 0
} catch {
    Write-Error "Failed to set up Virtual Display Driver: $_"
    exit 1
}
