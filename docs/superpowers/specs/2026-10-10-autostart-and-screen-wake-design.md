# OpenDisplay: Windows Autostart on Boot & Android Screen-Off Wake Design

## 1. Executive Summary & Goals
This specification defines the architecture for:
1. **Windows Boot Autostart**: Seamless background launching of `OpenDisplay.exe` on Windows boot/login via `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`, complete with an interactive toggle in the System Tray menu and auto-configuration in `OpenDisplay_Setup.bat`.
2. **Zero-Touch Tablet Screen-Off Wake & Keyguard Dismissal**: Automatically powering on the tablet screen from sleep/standby, dismissing the swipe lock screen, and bringing OpenDisplay to the front when connected via USB or when the PC boots, with **zero performance or battery overhead**.

---

## 2. Architecture & Data Flow

```
   ┌─────────────────────────────────────────────────────────────┐
   │ WINDOWS STARTUP                                             │
   │ 1. User logs into Windows                                   │
   │ 2. HKCU\...\Run launches "OpenDisplay.exe" in background    │
   │ 3. OpenDisplay sits in System Tray (0% CPU, virtual monitor │
   │    detached, waiting for tablet)                            │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ TABLET CONNECTED / PC DETECTS USB                           │
   │ 1. USBMonitorThread detects USB connection                  │
   │ 2. Host sends ADB keyevent 224 (KEYCODE_WAKEUP)             │
   │ 3. Host sends ADB wm dismiss-keyguard                       │
   │ 4. Host launches com.display.usbclient/.MainActivity        │
   └──────────────────────────────┬──────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ ANDROID CLIENT WAKEUP PIPELINE                              │
   │ 1. Manifest permissions: WAKE_LOCK, DISABLE_KEYGUARD        │
   │ 2. Activity flags: setShowWhenLocked(true),                 │
   │    setTurnScreenOn(true), requestDismissKeyguard()          │
   │ 3. PowerManager WakeLock momentarily powers on backlight    │
   │ 4. FLAG_KEEP_SCREEN_ON maintains display during streaming   │
   │ 5. Direct SurfaceView + MediaCodec decodes at < 1ms latency │
   └─────────────────────────────────────────────────────────────┘
```

---

## 3. Windows Boot Autostart Module (`server/autostart.py`)

### 3.1 Registry Key Specification
- **Registry Root**: `winreg.HKEY_CURRENT_USER`
- **Subkey**: `Software\Microsoft\Windows\CurrentVersion\Run`
- **Value Name**: `"OpenDisplay"`
- **Target Value**: Full path to executable or script:
  - If packaged executable exists: `r'"C:\path\to\OpenDisplay.exe"'`
  - If running from source: `r'pythonw.exe "C:\path\to\opendisplay_server.py"'`
- **Security & Privileges**: `HKCU` writes succeed without Administrator elevation or UAC prompts.

### 3.2 Module API (`server/autostart.py`)
- `get_executable_command() -> str`: Resolves the absolute path to `OpenDisplay.exe` or `pythonw.exe opendisplay_server.py`.
- `is_autostart_enabled() -> bool`: Queries the `Run` registry key; returns `True` if `"OpenDisplay"` is present and points to a valid path.
- `set_autostart(enable: bool) -> bool`:
  - If `enable == True`: Writes string value to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\OpenDisplay`.
  - If `enable == False`: Deletes value from registry key if present.

### 3.3 System Tray Menu Integration (`opendisplay_server.py`)
- In `SystemTray._wnd_proc`:
  - Query `is_autostart_enabled()`.
  - Append checkable menu item:
    - Label: `"Start with Windows"` with check flag `MF_CHECKED` if enabled, or `MF_UNCHECKED` if disabled.
    - Command ID: `1005`
  - When clicked: toggle autostart state via `set_autostart(not current_state)`.

### 3.4 Installer Integration (`OpenDisplay_Setup.bat`)
- In setup script, automatically register `OpenDisplay` autostart in the registry:
  ```bat
  echo [Step 3.5/4] Enabling Start with Windows on Boot...
  reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "OpenDisplay" /t REG_SZ /d "\"%~dp0dist\OpenDisplay\OpenDisplay.exe\"" /f >nul 2>nul
  ```

---

## 4. Android Zero-Touch Screen Wakeup & Keyguard Dismissal

### 4.1 Manifest Permissions (`android/app/src/main/AndroidManifest.xml`)
Add standard permissions:
```xml
<uses-permission android:name="android.permission.WAKE_LOCK" />
<uses-permission android:name="android.permission.DISABLE_KEYGUARD" />
```

### 4.2 Window Flags & Keyguard Dismissal (`MainActivity.java`)
In `onCreate()` and `onResume()`:
```java
// Keep screen illuminated while OpenDisplay is active
getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
    // Android 8.1+ (API 27+)
    setShowWhenLocked(true);
    setTurnScreenOn(true);
    KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
    if (km != null) {
        km.requestDismissKeyguard(this, null);
    }
} else {
    // Android 5.0 - 8.0 (API 21 - 26)
    getWindow().addFlags(
        WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED |
        WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD |
        WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
    );
}

// Momentarily acquire WakeLock to force physical display hardware to turn on from deep sleep
try {
    PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
    if (pm != null) {
        PowerManager.WakeLock wakeLock = pm.newWakeLock(
            PowerManager.FULL_WAKE_LOCK |
            PowerManager.ACQUIRE_CAUSES_WAKEUP |
            PowerManager.ON_AFTER_RELEASE,
            "OpenDisplay:ScreenWake"
        );
        wakeLock.acquire(2000); // Auto-release after 2 seconds
    }
} catch (Exception e) {
    Log.w(TAG, "WakeLock acquisition notice: " + e.getMessage());
}
```

### 4.3 Host USB Monitor Wakeup Signals (`opendisplay_server.py`)
In `OpenDisplayServer.launch_tablet_viewer()`:
Before launching the activity, send wake and keyguard dismissal commands:
```python
def launch_tablet_viewer(self):
    if not self.adb or not os.path.exists(self.adb):
        return
    try:
        # 1. Wake physical display from sleep (KEYCODE_WAKEUP = 224)
        subprocess.run(
            [self.adb, "shell", "input", "keyevent", "224"],
            capture_output=True, timeout=2, creationflags=0x08000000
        )
        # 2. Dismiss swipe keyguard
        subprocess.run(
            [self.adb, "shell", "wm", "dismiss-keyguard"],
            capture_output=True, timeout=2, creationflags=0x08000000
        )
        # 3. Bring MainActivity to foreground
        subprocess.run(
            [self.adb, "shell", "am", "start", "-n", "com.display.usbclient/.MainActivity"],
            capture_output=True, timeout=3, creationflags=0x08000000
        )
    except Exception as e:
        logger.warning(f"Failed waking tablet viewer: {e}")
```

---

## 5. Performance & Resource Impact Analysis

1. **Host PC (Idle on Boot)**:
   - Memory: ~15 MB RAM.
   - CPU: 0.0% CPU when tablet is unplugged.
   - GPU: Virtual display driver is detached; NVENC encoder does not run.
2. **Tablet Display**:
   - Decoding latency remains **< 1ms** (`0.67ms` on Lenovo Tab M8).
   - Once running, the display uses hardware `FLAG_KEEP_SCREEN_ON` (standard Android presentation mode).
   - When USB is disconnected or OpenDisplay exits, the WakeLock and window release, allowing the tablet to return to its standard display timeout and battery-saving sleep mode.

---

## 6. Testing & Verification Strategy

1. **Unit Tests**:
   - `tests/test_autostart.py`: Test `is_autostart_enabled()`, `set_autostart(True)`, `set_autostart(False)` with mocked `winreg`.
   - `tests/test_host_wake.py`: Verify `launch_tablet_viewer()` invokes `input keyevent 224` and `wm dismiss-keyguard`.
2. **On-Device Hardware Verification**:
   - Turn tablet screen completely off (`input keyevent 223`).
   - Run `launch_tablet_viewer()`.
   - Confirm via `dumpsys power` that display state switches to `ON` and OpenDisplay streams immediately.
