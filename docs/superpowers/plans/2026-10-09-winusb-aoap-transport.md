# Full Driver-Level AOAP & WinUSB Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement full driver-level Android Open Accessory Protocol (AOAP) and Windows WinUSB transport in OpenDisplay for driver-level plug-and-play, zero ADB requirements, sub-millisecond USB bulk transfer, and seamless TCP fallback.

**Architecture:** Pure Python WinUSB transport using `ctypes` (`winusb.dll` / `setupapi.dll`), Windows Driver INF (`opendisplay_aoap.inf`) binding `WinUSB.sys` to Google Accessory IDs (`18D1:2D00`/`2D01`), Android `UsbAccessory` + `UsbManager` auto-launch and streaming, integrated into host coordinate dispatch and capture streamer.

**Tech Stack:** Python 3.10, `ctypes`, Win32 API, `WinUSB.sys`, Android USB Accessory API (`UsbManager`, `UsbAccessory`), Java 8, MediaCodec, SurfaceView.

## Global Constraints
- Target tablet: Lenovo Tab M8 (TB-8505F), 1280x800.
- Host: Windows 10/11 x64.
- Windows user privileges: Zero admin elevation at runtime; driver installation handled via `pnputil.exe` or `devcon.exe`.
- Wire format: `[4 bytes big-endian total length][1 byte msgType][payload]`.
- No new external third-party binary DLLs required on Windows (pure `ctypes` on Windows native DLLs).

---

### Task 1: Windows AOAP Driver INF & Installer Script

**Files:**
- Create: `server/driver/aoap_bin/opendisplay_aoap.inf`
- Create: `install_aoap_driver.bat`
- Modify: `OpenDisplay_Setup.bat`
- Test: `tests/test_driver_inf.py`

**Interfaces:**
- Produces: `server/driver/aoap_bin/opendisplay_aoap.inf` with DeviceInterfaceGUID `{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}` and hardware IDs `USB\VID_18D1&PID_2D00` and `USB\VID_18D1&PID_2D01`.

- [x] **Step 1: Write the failing test for Driver INF structure and GUID validation**

```python
# tests/test_driver_inf.py
import os
import unittest

class TestDriverInf(unittest.TestCase):
    def setUp(self):
        self.inf_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'server', 'driver', 'aoap_bin', 'opendisplay_aoap.inf'
        )

    def test_inf_exists_and_contains_hardware_ids(self):
        self.assertTrue(os.path.exists(self.inf_path), "INF file must exist")
        with open(self.inf_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        self.assertIn("VID_18D1&PID_2D00", content)
        self.assertIn("VID_18D1&PID_2D01", content)
        self.assertIn("WinUSB.sys", content)
        self.assertIn("{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}", content)

if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_driver_inf.py`
Expected: FAIL with "INF file must exist"

- [x] **Step 3: Create Driver INF and install script**

Create `server/driver/aoap_bin/opendisplay_aoap.inf`:
```ini
;
; opendisplay_aoap.inf
; OpenDisplay AOAP WinUSB Driver
;

[Version]
Signature = "$Windows NT$"
Class     = USBDevice
ClassGUID = {88BAE032-5A81-49f0-BC3D-A4FF138216D6}
Provider  = %ManufacturerName%
DriverVer = 10/09/2026,1.1.0.0

[Manufacturer]
%ManufacturerName% = Standard,NTamd64

[Standard.NTamd64]
%DeviceName% = USB_Install,USB\VID_18D1&PID_2D00
%DeviceName% = USB_Install,USB\VID_18D1&PID_2D01,USB\VID_18D1&PID_2D01&MI_00

[USB_Install]
Include=winusb.inf
Needs=WINUSB.NT

[USB_Install.Services]
Include=winusb.inf
AddService=WinUsb,0x00000002,WinUsb_ServiceInstall

[WinUsb_ServiceInstall]
DisplayName     = %WinUsb_SvcDesc%
ServiceType     = 1
StartType       = 3
ErrorControl    = 1
ServiceBinary   = %12%\WinUSB.sys

[USB_Install.HW]
AddReg=Dev_AddReg

[Dev_AddReg]
HKR,,DeviceInterfaceGUIDs,0x10000,%GUID_DEVINTERFACE_AOAP%

[Strings]
ManufacturerName="OpenDisplay Project"
ClassName="Universal Serial Bus devices"
WinUsb_SvcDesc="OpenDisplay WinUSB Service"
DeviceName="OpenDisplay Android Accessory Interface"
GUID_DEVINTERFACE_AOAP="{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}"
```

Create `install_aoap_driver.bat`:
```bat
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
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_driver_inf.py`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add tests/test_driver_inf.py server/driver/aoap_bin/opendisplay_aoap.inf install_aoap_driver.bat
git commit -m "feat(driver): add opendisplay_aoap.inf and installer script"
```

---

### Task 2: Native Windows WinUSB Transport Module

**Files:**
- Create: `server/transport/winusb_transport.py`
- Test: `tests/test_winusb_transport.py`

**Interfaces:**
- Produces: `WinUsbTransport` class with methods:
  - `find_devices() -> list[str]`
  - `open_device(path: str) -> bool`
  - `close()`
  - `send_packet(msg_type: int, payload: bytes) -> bool`
  - `read_packet(timeout_ms: int = 1000) -> tuple[int, bytes] | None`
  - `switch_aoap(vendor_id: int, product_id: int) -> bool`

- [x] **Step 1: Write the failing unit test with mocks for WinUSB and SetupAPI**

```python
# tests/test_winusb_transport.py
import unittest
from unittest.mock import MagicMock, patch
from server.transport.winusb_transport import WinUsbTransport

class TestWinUsbTransport(unittest.TestCase):
    def test_packet_framing(self):
        transport = WinUsbTransport()
        frame = transport.frame_packet(0x02, b"\x00\x00\x00\x01\x65")
        # Total length is 1 + 5 = 6 (4 bytes big-endian: \x00\x00\x00\x06)
        # Type is \x02
        # Payload is \x00\x00\x00\x01\x65
        self.assertEqual(frame, b"\x00\x00\x00\x06\x02\x00\x00\x00\x01\x65")

    def test_unframe_packet(self):
        transport = WinUsbTransport()
        raw = b"\x00\x00\x00\x06\x02\x00\x00\x00\x01\x65"
        msg_type, payload = transport.unframe_packet(raw)
        self.assertEqual(msg_type, 0x02)
        self.assertEqual(payload, b"\x00\x00\x00\x01\x65")

if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_winusb_transport.py`
Expected: FAIL

- [x] **Step 3: Implement `WinUsbTransport` in `server/transport/winusb_transport.py`**

```python
# server/transport/winusb_transport.py
import ctypes
from ctypes import wintypes
import logging
import os
import struct

logger = logging.getLogger("OpenDisplay.WinUSB")

OPENDISPLAY_AOAP_GUID = "{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}"

class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', ctypes.c_ubyte * 8)
    ]

    @classmethod
    def from_str(cls, s: str):
        import uuid
        u = uuid.UUID(s)
        g = cls()
        g.Data1 = u.time_low
        g.Data2 = u.time_mid
        g.Data3 = u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        return g

class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('InterfaceClassGuid', GUID),
        ('Flags', wintypes.DWORD),
        ('Reserved', ctypes.c_void_p)
    ]

class WinUsbTransport:
    def __init__(self):
        self.handle = None
        self.winusb_handle = None
        self.out_pipe = 0x02
        self.in_pipe = 0x81
        self.is_connected = False
        self._setupapi = None
        self._winusb = None
        self._init_dlls()

    def _init_dlls(self):
        if os.name == 'nt':
            try:
                self._setupapi = ctypes.windll.setupapi
                self._winusb = ctypes.windll.winusb
            except Exception as e:
                logger.warning(f"Failed to load WinUSB DLLs: {e}")

    @staticmethod
    def frame_packet(msg_type: int, payload: bytes) -> bytes:
        total_len = 1 + len(payload)
        return struct.pack('>IB', total_len, msg_type) + payload

    @staticmethod
    def unframe_packet(raw_bytes: bytes) -> tuple[int, bytes]:
        if len(raw_bytes) < 5:
            raise ValueError("Packet too short")
        total_len, msg_type = struct.unpack('>IB', raw_bytes[:5])
        payload = raw_bytes[5:4 + total_len]
        return msg_type, payload

    def find_devices(self) -> list[str]:
        if not self._setupapi:
            return []
        guid = GUID.from_str(OPENDISPLAY_AOAP_GUID)
        DIGCF_PRESENT = 0x02
        DIGCF_DEVICEINTERFACE = 0x10
        self._setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
        hdev = self._setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
        if not hdev or hdev == ctypes.c_void_p(-1).value:
            return []

        devices = []
        iface = SP_DEVICE_INTERFACE_DATA()
        iface.cbSize = ctypes.sizeof(iface)
        idx = 0
        while self._setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid), idx, ctypes.byref(iface)):
            req_size = wintypes.DWORD(0)
            self._setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(iface), None, 0, ctypes.byref(req_size), None)
            if req_size.value > 0:
                detail_buf = ctypes.create_string_buffer(req_size.value)
                # cbSize is 8 bytes on x64
                struct.pack_into('I', detail_buf, 0, 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5)
                if self._setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(iface), detail_buf, req_size.value, None, None):
                    path = ctypes.wstring_at(ctypes.addressof(detail_buf) + 4)
                    devices.append(path)
            idx += 1
        self._setupapi.SetupDiDestroyDeviceInfoList(hdev)
        return devices

    def open_device(self, path: str) -> bool:
        if not self._winusb or not path:
            return False
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x01
        FILE_SHARE_WRITE = 0x02
        OPEN_EXISTING = 3
        FILE_FLAG_OVERLAPPED = 0x40000000

        self.handle = ctypes.windll.kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None
        )
        if self.handle == -1 or not self.handle:
            logger.warning(f"Failed to open device handle for {path}")
            return False

        h_winusb = ctypes.c_void_p()
        if not self._winusb.WinUsb_Initialize(self.handle, ctypes.byref(h_winusb)):
            logger.warning("WinUsb_Initialize failed")
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None
            return False

        self.winusb_handle = h_winusb
        self.is_connected = True
        logger.info(f"WinUSB device opened successfully: {path}")
        return True

    def send_packet(self, msg_type: int, payload: bytes) -> bool:
        if not self.is_connected or not self.winusb_handle:
            return False
        data = self.frame_packet(msg_type, payload)
        written = wintypes.DWORD(0)
        res = self._winusb.WinUsb_WritePipe(
            self.winusb_handle,
            ctypes.c_ubyte(self.out_pipe),
            data,
            len(data),
            ctypes.byref(written),
            None
        )
        return bool(res and written.value == len(data))

    def read_packet(self) -> tuple[int, bytes] | None:
        if not self.is_connected or not self.winusb_handle:
            return None
        buf = ctypes.create_string_buffer(4096)
        transferred = wintypes.DWORD(0)
        res = self._winusb.WinUsb_ReadPipe(
            self.winusb_handle,
            ctypes.c_ubyte(self.in_pipe),
            buf,
            4096,
            ctypes.byref(transferred),
            None
        )
        if res and transferred.value >= 5:
            return self.unframe_packet(buf.raw[:transferred.value])
        return None

    def close(self):
        self.is_connected = False
        if self.winusb_handle:
            self._winusb.WinUsb_Free(self.winusb_handle)
            self.winusb_handle = None
        if self.handle:
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None
```

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_winusb_transport.py`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add tests/test_winusb_transport.py server/transport/winusb_transport.py
git commit -m "feat(transport): implement pure python winusb transport"
```

---

### Task 3: Android UsbAccessory & Auto-Launch Pipeline

**Files:**
- Create: `android/app/src/main/res/xml/accessory_filter.xml`
- Modify: `android/app/src/main/AndroidManifest.xml`
- Modify: `android/app/src/main/java/com/display/usbclient/StreamReceiver.java`
- Modify: `android/app/src/main/java/com/display/usbclient/MainActivity.java`
- Test: Build APK using `build_apk.ps1`

**Interfaces:**
- Produces: `StreamReceiver(UsbAccessory accessory, Context context, StreamListener listener)` constructor supporting native file descriptors and automatic failover to TCP socket.

- [x] **Step 1: Create `accessory_filter.xml`**

Create `android/app/src/main/res/xml/accessory_filter.xml`:
```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <usb-accessory
        manufacturer="OpenDisplay"
        model="OpenDisplay"
        version="1.1" />
</resources>
```

- [x] **Step 2: Update `AndroidManifest.xml`**

Add `<uses-feature android:name="android.hardware.usb.accessory" android:required="false" />` and intent filter:
```xml
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize"
            android:screenOrientation="landscape"
            android:theme="@android:style/Theme.NoTitleBar.Fullscreen">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
            <intent-filter>
                <action android:name="android.hardware.usb.action.USB_ACCESSORY_ATTACHED" />
            </intent-filter>
            <meta-data
                android:name="android.hardware.usb.action.USB_ACCESSORY_ATTACHED"
                android:resource="@xml/accessory_filter" />
        </activity>
```

- [x] **Step 3: Update `StreamReceiver.java` to support `UsbAccessory` streams**

Add secondary constructor and accessory lifecycle:
```java
    private UsbAccessory accessory;
    private Context context;
    private ParcelFileDescriptor pfd;

    public StreamReceiver(UsbAccessory accessory, Context context, StreamListener listener) {
        this.accessory = accessory;
        this.context = context;
        this.listener = listener;
        this.touchExecutor = new ThreadPoolExecutor(
            1, 1, 0L, TimeUnit.MILLISECONDS,
            new LinkedBlockingQueue<>(16),
            new ThreadPoolExecutor.DiscardOldestPolicy()
        );
    }
```
In `run()`: if `accessory != null`, call `UsbManager.openAccessory(accessory)` and wrap `FileInputStream` / `FileOutputStream` instead of Socket.

- [x] **Step 4: Update `MainActivity.java` to detect `UsbAccessory`**

In `initReceiver()`:
```java
        UsbManager usbManager = (UsbManager) getSystemService(Context.USB_SERVICE);
        UsbAccessory accessory = getIntent().getParcelableExtra(UsbManager.EXTRA_ACCESSORY);
        if (accessory == null && usbManager != null) {
            UsbAccessory[] list = usbManager.getAccessoryList();
            if (list != null && list.length > 0) {
                accessory = list[0];
            }
        }

        if (accessory != null) {
            Log.i(TAG, "Opening StreamReceiver in AOAP Accessory mode");
            streamReceiver = new StreamReceiver(accessory, this, this);
        } else {
            Log.i(TAG, "Opening StreamReceiver in TCP mode (127.0.0.1:7070)");
            streamReceiver = new StreamReceiver("127.0.0.1", 7070, this);
        }
```

- [x] **Step 5: Verify build with `build_apk.ps1` and commit**

Run: `powershell -ExecutionPolicy Bypass -File build_apk.ps1`
Expected: `SUCCESS: OpenDisplay.apk created`

```bash
git add android/ OpenDisplay.apk
git commit -m "feat(android): implement usb accessory receiver and manifest intent filter"
```

---

### Task 4: Host Server Coordination & Dual-Transport Integration

**Files:**
- Modify: `opendisplay_server.py`
- Modify: `server/streamer.py`
- Test: `tests/test_streamer.py`

**Interfaces:**
- Consumes: `WinUsbTransport` from `server/transport/winusb_transport.py`
- Produces: Integrated dual-transport support streaming GPU encoded frames to WinUSB bulk OUT if present, while concurrently serving TCP 7070.

- [x] **Step 1: Write unit test verifying dual-transport frame dispatch in `server/streamer.py`**

```python
# In tests/test_streamer.py
def test_dual_transport_dispatch(self):
    mock_winusb = MagicMock()
    mock_winusb.is_connected = True
    streamer = Streamer(port=0, auto_forward=False)
    streamer.winusb_transport = mock_winusb
    streamer.broadcast_packet(0x02, b"\x00\x00\x00\x01\x65")
    mock_winusb.send_packet.assert_called_with(0x02, b"\x00\x00\x00\x01\x65")
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_streamer.py`
Expected: FAIL

- [x] **Step 3: Update `Streamer` and `OpenDisplayServer`**

In `server/streamer.py`:
- Accept optional `winusb_transport`.
- In `broadcast_packet()`: send to both `self._clients` (TCP sockets) and `self.winusb_transport` (USB Bulk).
- In `start_background()`: spawn WinUSB reader thread forwarding incoming touch packets (`0x04`) to `self.handle_input_event()`.

In `opendisplay_server.py`:
- Initialize `WinUsbTransport()`.
- Scan for WinUSB devices in `UsbMonitorThread`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m unittest discover -s tests`
Expected: All 50+ tests pass.

- [x] **Step 5: Commit**

```bash
git add server/streamer.py opendisplay_server.py tests/test_streamer.py
git commit -m "feat(server): integrate dual-transport winusb bulk and tcp streaming"
```

---

### Task 5: End-to-End Build, Test Verification & Packaging

**Files:**
- Modify: `OpenDisplay_Setup.bat`
- Test: Tablet live deployment & verification

- [x] **Step 1: Update `OpenDisplay_Setup.bat` with AOAP driver installation**

Add step registering `opendisplay_aoap.inf` during setup if not already registered.

- [x] **Step 2: Compile fresh Windows binary & package release**

Run PyInstaller and build `OpenDisplay-v1.1.0-windows-x64.zip`.

- [x] **Step 3: Install APK on tablet and verify live connection**

Install `OpenDisplay.apk` onto Lenovo Tab M8 via ADB, verify app launch and decoding.

- [x] **Step 4: Final verification and commit**

```bash
git commit -am "chore(release): package full aoap and winusb transport update"
git push origin main
```
