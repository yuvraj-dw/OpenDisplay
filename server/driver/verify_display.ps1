Add-Type -AssemblyName System.Windows.Forms
$screens = [System.Windows.Forms.Screen]::AllScreens

Write-Output "Found $($screens.Count) monitor(s):"
foreach ($s in $screens) {
    Write-Output " - Device: $($s.DeviceName), Bounds: $($s.Bounds.Width)x$($s.Bounds.Height), Primary: $($s.Primary)"
}

if ($screens.Count -ge 2) {
    Write-Output "SUCCESS: Secondary display is active."
    exit 0
} else {
    Write-Output "WARNING: Only $($screens.Count) display(s) detected (secondary display not detected)."
    exit 1
}
