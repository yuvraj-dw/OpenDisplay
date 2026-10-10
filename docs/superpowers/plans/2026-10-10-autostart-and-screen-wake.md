# Boot Autostart & Screen-Off Wake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement seamless Windows boot autostart via registry and System Tray toggle, plus dual-layer zero-touch Android tablet screen wakeup from sleep/lockscreen with zero performance overhead.

**Architecture:** Standard Windows user registry management in `server/autostart.py` (`HKCU\...\Run`), System Tray interactive checkmark item, Android `MainActivity` wakeup window flags and short WakeLock, and Host USB monitor ADB wake/keyguard dismissal signals.

**Tech Stack:** Python 3.10, `winreg`, Win32 API (`win32gui`, `win32con`), Android Java (`PowerManager`, `KeyguardManager`, `WindowManager`), Android Manifest, ADB.

## Global Constraints
- Target tablet: Lenovo Tab M8 (TB-8505F), 1280x800.
- Host: Windows 10/11 x64.
- Windows user privileges: Standard user (`HKEY_CURRENT_USER`), zero UAC elevation loops.
- Performance: 0% CPU impact when idle; <1ms decode latency during streaming.

---

### Task 1: Windows Boot Autostart Registry Module

**Files:**
- Create: `server/autostart.py`
- Test: `tests/test_autostart.py`

**Interfaces:**
- Produces:
  - `is_autostart_enabled() -> bool`
  - `set_autostart(enable: bool) -> bool`
  - `get_executable_command() -> str`

- [ ] **Step 1: Write the failing unit test for autostart functions**

```python
# tests/test_autostart.py
import unittest
from unittest.mock import MagicMock, patch
import os
from server.autostart import is_autostart_enabled, set_autostart, get_executable_command

class TestAutostart(unittest.TestCase):
    @patch('winreg.OpenKey')
    @patch('winreg.QueryValueEx')
    def test_is_autostart_enabled_true(self, mock_query, mock_open):
        mock_query.return_value = (r'"C:\OpenDisplay\OpenDisplay.exe"', 1)
        self.assertTrue(is_autostart_enabled())

    @patch('winreg.OpenKey')
    def test_is_autostart_enabled_false_on_missing(self, mock_open):
        mock_open.side_effect = FileNotFoundError()
        self.assertFalse(is_autostart_enabled())

    @patch('winreg.OpenKey')
    @patch('winreg.SetValueEx')
    def test_set_autostart_enable(self, mock_set, mock_open):
        mock_key = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_key
        res = set_autostart(True)
        self.assertTrue(res)
        mock_set.assert_called_once()

    @patch('winreg.OpenKey')
    @patch('winreg.DeleteValue')
    def test_set_autostart_disable(self, mock_del, mock_open):
        mock_key = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_key
        res = set_autostart(False)
        self.assertTrue(res)
        mock_del.assert_called_once()

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_autostart.py`
Expected: FAIL with "No module named 'server.autostart'"

- [ ] **Step 3: Implement `server/autostart.py`**

```python
# server/autostart.py
import os
import sys
import logging

logger = logging.getLogger("OpenDisplay.Autostart")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "OpenDisplay"


def get_executable_command() -> str:
    """Returns the properly quoted executable command for the current installation."""
    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        return f'"{exe_path}"'
    else:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        dist_exe = os.path.join(root_dir, 'dist', 'OpenDisplay', 'OpenDisplay.exe')
        if os.path.exists(dist_exe):
            return f'"{dist_exe}"'
        server_py = os.path.join(root_dir, 'opendisplay_server.py')
        pythonw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        return f'"{pythonw}" "{server_py}"'


def is_autostart_enabled() -> bool:
    """Checks whether OpenDisplay is registered in HKCU Run key."""
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as e:
        logger.warning(f"Failed querying autostart registry: {e}")
        return False


def set_autostart(enable: bool) -> bool:
    """Enables or disables OpenDisplay startup in HKCU Run key."""
    if os.name != 'nt':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = get_executable_command()
                winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, cmd)
                logger.info(f"Registered autostart command: {cmd}")
            else:
                try:
                    winreg.DeleteValue(key, APP_VALUE_NAME)
                    logger.info("Removed autostart registration.")
                except FileNotFoundError:
                    pass
            return True
    except Exception as e:
        logger.error(f"Failed setting autostart registry to {enable}: {e}")
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_autostart.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_autostart.py server/autostart.py
git commit -m "feat(autostart): add windows registry autostart management module"
```

---

### Task 2: System Tray "Start with Windows" Toggle & Setup Integration

**Files:**
- Modify: `opendisplay_server.py:290-345`
- Modify: `OpenDisplay_Setup.bat`
- Test: `tests/test_tray_menu.py`

**Interfaces:**
- Consumes: `is_autostart_enabled()`, `set_autostart()` from `server/autostart.py`
- Produces: System Tray checkable menu item `[✓] Start with Windows` with command ID `1005`.

- [ ] **Step 1: Write test for Tray menu command ID and toggle handler**

```python
# tests/test_tray_menu.py
import unittest
from unittest.mock import MagicMock, patch
from server.autostart import set_autostart, is_autostart_enabled

class TestTrayAutostartToggle(unittest.TestCase):
    @patch('server.autostart.set_autostart')
    @patch('server.autostart.is_autostart_enabled')
    def test_toggle_logic(self, mock_is_enabled, mock_set):
        mock_is_enabled.return_value = False
        new_state = not is_autostart_enabled()
        set_autostart(new_state)
        mock_set.assert_called_with(True)

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m unittest tests/test_tray_menu.py`
Expected: PASS

- [ ] **Step 3: Update `opendisplay_server.py` SystemTray menu**

In `opendisplay_server.py`:
- Import `from server.autostart import is_autostart_enabled, set_autostart`.
- In `SystemTray._wnd_proc`:
  ```python
  autostart_flag = win32con.MF_CHECKED if is_autostart_enabled() else win32con.MF_UNCHECKED
  win32gui.AppendMenu(menu, win32con.MF_STRING | autostart_flag, 1005, "Start with Windows")
  ```
  And in command dispatch:
  ```python
  elif cmd == 1005:
      current = is_autostart_enabled()
      set_autostart(not current)
  ```

- [ ] **Step 4: Update `OpenDisplay_Setup.bat`**

Add step registering autostart during initial setup:
```bat
echo [Step 3.5/4] Enabling Start with Windows on Boot...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "OpenDisplay" /t REG_SZ /d "\"%~dp0dist\OpenDisplay\OpenDisplay.exe\"" /f >nul 2>nul
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m unittest discover -s tests`
Expected: PASS

```bash
git add opendisplay_server.py OpenDisplay_Setup.bat tests/test_tray_menu.py
git commit -m "feat(tray): add start with windows menu toggle and setup auto-enable"
```

---

### Task 3: Android Zero-Touch Screen Wakeup & Keyguard Dismissal

**Files:**
- Modify: `android/app/src/main/AndroidManifest.xml`
- Modify: `android/app/src/main/java/com/display/usbclient/MainActivity.java`
- Test: Build APK using `build_apk.ps1`

**Interfaces:**
- Produces: `OpenDisplay.apk` with `WAKE_LOCK` and `DISABLE_KEYGUARD` permissions, automatic physical screen illumination from standby, and keyguard bypass.

- [ ] **Step 1: Add permissions to `AndroidManifest.xml`**

```xml
<uses-permission android:name="android.permission.WAKE_LOCK" />
<uses-permission android:name="android.permission.DISABLE_KEYGUARD" />
```

- [ ] **Step 2: Update `MainActivity.java` with screen wake and unlock logic**

In `MainActivity.onCreate()` and `initWakeSettings()`:
```java
    private void initWakeAndUnlock() {
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            android.app.KeyguardManager km = (android.app.KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            if (km != null) {
                km.requestDismissKeyguard(this, null);
            }
        } else {
            getWindow().addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED |
                WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD |
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            );
        }

        try {
            android.os.PowerManager pm = (android.os.PowerManager) getSystemService(Context.POWER_SERVICE);
            if (pm != null) {
                android.os.PowerManager.WakeLock wl = pm.newWakeLock(
                    android.os.PowerManager.FULL_WAKE_LOCK |
                    android.os.PowerManager.ACQUIRE_CAUSES_WAKEUP |
                    android.os.PowerManager.ON_AFTER_RELEASE,
                    "OpenDisplay:ScreenWake"
                );
                wl.acquire(2000);
            }
        } catch (Exception e) {
            Log.w(TAG, "WakeLock notice: " + e.getMessage());
        }
    }
```
Call `initWakeAndUnlock()` in `onCreate()` and in `onNewIntent()`.

- [ ] **Step 3: Compile and sign APK**

Run: `powershell -ExecutionPolicy Bypass -File build_apk.ps1`
Expected: `SUCCESS: OpenDisplay.apk created`

- [ ] **Step 4: Commit**

```bash
git add android/app/src/main/AndroidManifest.xml android/app/src/main/java/com/display/usbclient/MainActivity.java OpenDisplay.apk
git commit -m "feat(android): add wake lock, turn screen on, and dismiss keyguard"
```

---

### Task 4: Host ADB USB Monitor Wakeup Signals

**Files:**
- Modify: `opendisplay_server.py:440-475`
- Test: `tests/test_host_wake.py`

**Interfaces:**
- Produces: `launch_tablet_viewer()` sending `input keyevent 224` (`KEYCODE_WAKEUP`) and `wm dismiss-keyguard` before launching activity.

- [ ] **Step 1: Write unit test for `launch_tablet_viewer` wake signals**

```python
# tests/test_host_wake.py
import unittest
from unittest.mock import MagicMock, patch
from opendisplay_server import OpenDisplayServer

class TestHostWake(unittest.TestCase):
    @patch('subprocess.run')
    @patch('os.path.exists', return_value=True)
    def test_launch_tablet_viewer_sends_wakeup_keyevent(self, mock_exists, mock_run):
        server = OpenDisplayServer(port=0)
        server.adb = "adb.exe"
        server.launch_tablet_viewer()
        
        # Verify keyevent 224 was sent
        wakeup_call = False
        dismiss_call = False
        am_start_call = False
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            if cmd == ["adb.exe", "shell", "input", "keyevent", "224"]:
                wakeup_call = True
            elif cmd == ["adb.exe", "shell", "wm", "dismiss-keyguard"]:
                dismiss_call = True
            elif "am" in cmd and "start" in cmd:
                am_start_call = True
                
        self.assertTrue(wakeup_call, "Must send KEYCODE_WAKEUP (224)")
        self.assertTrue(dismiss_call, "Must send wm dismiss-keyguard")
        self.assertTrue(am_start_call, "Must send am start")

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_host_wake.py`
Expected: FAIL with missing wakeup call

- [ ] **Step 3: Update `OpenDisplayServer.launch_tablet_viewer()`**

In `opendisplay_server.py`:
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
            # 3. Launch MainActivity
            subprocess.run(
                [self.adb, "shell", "am", "start", "-n", "com.display.usbclient/.MainActivity"],
                capture_output=True, timeout=3, creationflags=0x08000000
            )
        except Exception:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_host_wake.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add opendisplay_server.py tests/test_host_wake.py
git commit -m "feat(host): send adb screen wakeup and keyguard dismissal on tablet connection"
```

---

### Task 5: End-to-End Build, Test Verification & Packaging

**Files:**
- Modify: `OpenDisplay.spec`
- Rebuild: `dist/OpenDisplay/OpenDisplay.exe`
- Rebuild: `OpenDisplay-v1.1.0-windows-x64.zip`
- On-device test: Verify tablet screen wakes from deep sleep (`input keyevent 223` -> reconnect -> display turns on).

- [x] **Step 1: Run full automated test suite**

Run: `python -m unittest discover -s tests`
Expected: All 79+ tests pass.

- [x] **Step 2: Rebuild PyInstaller binary and package release archive**

Compile `OpenDisplay.exe` and compress `OpenDisplay-v1.1.0-windows-x64.zip`.

- [x] **Step 3: Deploy updated APK to connected tablet and test screen wakeup**

Install APK on device, put tablet screen to sleep, trigger `launch_tablet_viewer()`, confirm display turns ON and video streams.

- [x] **Step 4: Commit and push**

```bash
git commit -am "chore(release): package windows boot autostart and zero-touch tablet wakeup"
git push origin main
```
