# build_apk.ps1 - Automated Standalone Android APK Builder
$ErrorActionPreference = "Stop"

$rootDir = $PSScriptRoot
$toolsDir = Join-Path $rootDir "build_tools"
$androidSrc = Join-Path $rootDir "android\app\src\main"
$outDir = Join-Path $rootDir "android\build\outputs"
New-Item -ItemType Directory -Path $toolsDir, $outDir -Force | Out-Null

Write-Host "========================================================"
Write-Host "          OpenDisplay Android APK Builder               "
Write-Host "========================================================"

# 1. Download Android SDK jar if missing
$androidJar = Join-Path $toolsDir "android.jar"
if (-not (Test-Path $androidJar)) {
    Write-Host "[1/5] Downloading android.jar (Android 30 SDK)..."
    curl.exe -sL "https://raw.githubusercontent.com/Sable/android-platforms/master/android-30/android.jar" -o $androidJar
}

# 2. Download R8 / D8 dex compiler if missing
$r8Jar = Join-Path $toolsDir "r8.jar"
if (-not (Test-Path $r8Jar)) {
    Write-Host "[2/5] Downloading D8 / R8 DEX compiler..."
    curl.exe -sL "https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.2.42/r8-8.2.42.jar" -o $r8Jar
}

# 3. Download AAPT2 if missing
$aaptZip = Join-Path $toolsDir "aapt2.jar"
$aaptExe = Join-Path $toolsDir "aapt2.exe"
if (-not (Test-Path $aaptExe)) {
    Write-Host "[3/5] Downloading AAPT2 asset packaging tool..."
    curl.exe -sL "https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/8.2.2-10154469/aapt2-8.2.2-10154469-windows.jar" -o $aaptZip
    & "C:\Program Files\7-Zip\7z.exe" e $aaptZip "aapt2.exe" -o"$toolsDir" -y | Out-Null
}

# 4. Download Portable OpenJDK 17 if java/javac not found
$javacCmd = (Get-Command javac -ErrorAction SilentlyContinue).Source
$javaCmd = (Get-Command java -ErrorAction SilentlyContinue).Source

$jdkDir = Join-Path $toolsDir "jdk"
if (-not $javacCmd) {
    $jdkBin = Join-Path $jdkDir "bin\javac.exe"
    if (-not (Test-Path $jdkBin)) {
        Write-Host "[4/5] Downloading portable OpenJDK 17..."
        $jdkZip = Join-Path $toolsDir "openjdk17.zip"
        curl.exe -sL "https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.10%2B7/OpenJDK17U-jdk_x64_windows_hotspot_17.0.10_7.zip" -o $jdkZip
        Write-Host "Extracting OpenJDK 17..."
        & "C:\Program Files\7-Zip\7z.exe" x $jdkZip -o"$toolsDir\jdk_temp" -y | Out-Null
        $extracted = (Get-ChildItem "$toolsDir\jdk_temp\jdk*" -Directory)[0].FullName
        Move-Item -Path $extracted -Destination $jdkDir
        Remove-Item "$toolsDir\jdk_temp", $jdkZip -Recurse -Force
    }
    $javacCmd = Join-Path $jdkDir "bin\javac.exe"
    $javaCmd = Join-Path $jdkDir "bin\java.exe"
}

Write-Host "[5/5] Compiling and Packaging OpenDisplay.apk..."
$classesDir = Join-Path $toolsDir "classes"
Remove-Item $classesDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $classesDir -Force | Out-Null

# Compile Java sources
$javaFiles = Get-ChildItem "$androidSrc\java\com\display\usbclient\*.java" | ForEach-Object { $_.FullName }
& $javacCmd -cp $androidJar -d $classesDir -source 8 -target 8 $javaFiles

# Compile classes to classes.dex with D8
$dexDir = Join-Path $toolsDir "dex"
Remove-Item $dexDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $dexDir -Force | Out-Null
$compiledClasses = Get-ChildItem "$classesDir\com\display\usbclient\*.class" | ForEach-Object { $_.FullName }
& $javaCmd -cp $r8Jar com.android.tools.r8.D8 --lib $androidJar --output $dexDir --min-api 26 $compiledClasses

# Compile Android resources and link APK with AAPT2
$manifestXml = Join-Path $androidSrc "AndroidManifest.xml"
$compiledRes = Join-Path $toolsDir "compiled_res.zip"
Remove-Item $compiledRes -Force -ErrorAction SilentlyContinue
& $aaptExe compile --dir "$androidSrc\res" -o $compiledRes

$compiledApk = Join-Path $outDir "OpenDisplay_unaligned.apk"
$finalApk = Join-Path $rootDir "OpenDisplay.apk"
Remove-Item $compiledApk, $finalApk -Force -ErrorAction SilentlyContinue

& $aaptExe link -I $androidJar -R $compiledRes --min-sdk-version 26 --target-sdk-version 30 --manifest $manifestXml -o $compiledApk --auto-add-overlay

# Add classes.dex into APK
& "C:\Program Files\7-Zip\7z.exe" a -tzip $compiledApk (Join-Path $dexDir "classes.dex") | Out-Null

# Sign APK with debug key
$keytoolCmd = (Join-Path (Split-Path $javacCmd) "keytool.exe")
$keystore = Join-Path $toolsDir "debug.keystore"
if (-not (Test-Path $keystore)) {
    & $keytoolCmd -genkeypair -alias androiddebugkey -keypass android -keystore $keystore -storepass android -dname "CN=Android Debug,O=Android,C=US" -validity 10000 -keyalg RSA -keysize 2048
}

# Sign with apksigner if available or jarsigner
$jarsignerCmd = (Join-Path (Split-Path $javacCmd) "jarsigner.exe")
& $jarsignerCmd -keystore $keystore -storepass android -keypass android -signedjar $finalApk $compiledApk androiddebugkey

Write-Host "========================================================"
Write-Host "SUCCESS: OpenDisplay.apk created at:"
Write-Host " $finalApk"
Write-Host "========================================================"
