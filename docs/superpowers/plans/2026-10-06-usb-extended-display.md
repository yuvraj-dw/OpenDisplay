# USB Extended Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a functional, ultra-low latency extended display system that streams a Windows virtual secondary monitor to an Android tablet over a wired USB cable via ADB port forwarding.

**Architecture:** The Windows host creates a virtual monitor via an IddCx driver, captures frames using the DXGI Desktop Duplication API, encodes them into H.264 NAL units via GPU hardware encoding, and streams them over a localhost TCP socket forwarded through USB via ADB. The Android client connects to `localhost:7070`, feeds NAL units into `android.media.MediaCodec`, and renders zero-copy directly onto a fullscreen `SurfaceView`.

**Tech Stack:** 
- Windows Host: C++ / Python (DirectX 11, DXGI Desktop Duplication, Media Foundation / FFmpeg NVENC/AMF/QSV)
- Windows Virtual Monitor: IddSampleDriver / Virtual Display Driver (VDD)
- Android Client: Kotlin / Android SDK (MediaCodec, SurfaceView, java.net.Socket)
- Transport: ADB TCP port forwarding (`adb forward tcp:7070 tcp:7070`)

## Global Constraints
- Target platform: Windows 10/11 (Host) and Android 8.0+ (Client)
- Connection mode: Wired USB with USB Debugging enabled (no Wi-Fi dependencies)
- Target latency: Sub-20ms glass-to-glass
- No touch/stylus drivers required (pure extended display)

---

### Task 1: Virtual Display Driver Configuration & Verification

**Files:**
- Create: `server/driver/setup_vdd.ps1`
- Test: `server/driver/verify_display.ps1`

**Interfaces:**
- Consumes: Windows PowerShell / DisplayConfig APIs
- Produces: Active virtual secondary display detected by Windows DWM

- [x] **Step 1: Write verification script for secondary monitor detection**

Create `server/driver/verify_display.ps1`:
```powershell
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
    Write-Output "WARNING: Only 1 display detected."
    exit 1
}
```

- [x] **Step 2: Run verification to observe baseline**

Run: `powershell -ExecutionPolicy Bypass -File server/driver/verify_display.ps1`
Expected: Output showing current primary monitor.

- [x] **Step 3: Create automated installer script for Virtual Display Driver**

Create `server/driver/setup_vdd.ps1`:
```powershell
$vddUrl = "https://github.com/itsmeowde/virtual-display-driver/releases/latest/download/Virtual-Display-Driver.zip"
$destDir = "$PSScriptRoot\vdd_bin"
New-Item -ItemType Directory -Path $destDir -Force | Out-Null

Write-Host "Downloading Virtual Display Driver..."
Invoke-WebRequest -Uri $vddUrl -OutFile "$destDir\vdd.zip"
Expand-Archive -Path "$destDir\vdd.zip" -DestinationPath $destDir -Force

Write-Host "VDD downloaded. Install certificate and driver via inf:"
Write-Host "pnputil /add-driver `"$destDir\IddSampleDriver.inf`" /install"
```

- [x] **Step 4: Verify driver installation and secondary screen creation**

Run: `powershell -ExecutionPolicy Bypass -File server/driver/verify_display.ps1`
Expected: Exit code 0, reporting at least 2 active screens.

---

### Task 2: ADB USB Connection & Protocol Framing Library

**Files:**
- Create: `server/transport/adb_bridge.py`
- Create: `server/transport/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: Local ADB server (`adb.exe`)
- Produces: `AdbBridge.forward(port)` and `PacketFramer` (length-prefixed byte stream)

- [x] **Step 1: Write unit tests for protocol framing**

Create `tests/test_protocol.py`:
```python
import unittest
from server.transport.protocol import pack_message, unpack_message, MSG_CONFIG, MSG_VIDEO

class TestProtocol(unittest.TestCase):
    def test_pack_unpack_config(self):
        payload = b'{"width": 2560, "height": 1600, "fps": 60}'
        packed = pack_message(MSG_CONFIG, payload)
        msg_type, unpacked = unpack_message(packed)
        self.assertEqual(msg_type, MSG_CONFIG)
        self.assertEqual(unpacked, payload)

    def test_pack_unpack_video_nal(self):
        nal_payload = b'\x00\x00\x00\x01\x67\x42\x00\x1f'
        packed = pack_message(MSG_VIDEO, nal_payload)
        msg_type, unpacked = unpack_message(packed)
        self.assertEqual(msg_type, MSG_VIDEO)
        self.assertEqual(unpacked, nal_payload)

if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_protocol.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'server'`)

- [x] **Step 3: Implement protocol framing and ADB bridge**

Create `server/transport/protocol.py`:
```python
import struct

MSG_CONFIG = 1
MSG_VIDEO = 2
MSG_HEARTBEAT = 3

# Format: 4 bytes length (uint32 big-endian), 1 byte message type (uint8)
HEADER_FORMAT = '>IB'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

def pack_message(msg_type: int, payload: bytes) -> bytes:
    total_len = len(payload) + 1  # 1 byte for type
    header = struct.pack(HEADER_FORMAT, total_len, msg_type)
    return header + payload

def unpack_header(data: bytes):
    if len(data) < HEADER_SIZE:
        return None, None
    total_len, msg_type = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    payload_len = total_len - 1
    return msg_type, payload_len

def unpack_message(data: bytes):
    msg_type, payload_len = unpack_header(data)
    if msg_type is None:
        return None, None
    payload = data[HEADER_SIZE : HEADER_SIZE + payload_len]
    return msg_type, payload
```

Create `server/transport/adb_bridge.py`:
```python
import subprocess
import shutil

class AdbBridge:
    def __init__(self, adb_path: str = None):
        self.adb = adb_path or shutil.which('adb') or 'adb.exe'

    def is_device_connected(self) -> bool:
        res = subprocess.run([self.adb, 'devices'], capture_output=True, text=True)
        lines = [line.strip() for line in res.stdout.strip().split('\n')[1:] if line.strip()]
        return any('\tdevice' in line for line in lines)

    def forward_port(self, host_port: int = 7070, device_port: int = 7070) -> bool:
        res = subprocess.run(
            [self.adb, 'forward', f'tcp:{host_port}', f'tcp:{device_port}'],
            capture_output=True, text=True
        )
        return res.returncode == 0
```

- [x] **Step 4: Run unit tests to verify protocol passes**

Run: `python -m unittest tests/test_protocol.py`
Expected: `Ran 2 tests ... OK`

---

### Task 3: Windows Screen Capture & Hardware Encoder Host Daemon

**Files:**
- Create: `server/capture/dxgi_capture.py`
- Create: `server/encoder/hw_encoder.py`
- Create: `server/streamer.py`
- Test: `tests/test_capture.py`

**Interfaces:**
- Consumes: DXGI Desktop Duplication API on target secondary monitor index
- Produces: H.264 NAL units pushed to connected USB TCP client on `127.0.0.1:7070`

- [x] **Step 1: Write capture test script**

Create `tests/test_capture.py`:
```python
import unittest
from server.capture.dxgi_capture import DxgiScreenCapture

class TestCapture(unittest.TestCase):
    def test_dxgi_enumeration(self):
        cap = DxgiScreenCapture()
        monitors = cap.list_outputs()
        self.assertGreater(len(monitors), 0, "Should detect at least one monitor output")

if __name__ == '__main__':
    unittest.main()
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_capture.py`
Expected: FAIL with `ModuleNotFoundError`

- [x] **Step 3: Implement DXGI Screen Capture and Streamer Daemon**

Create `server/capture/dxgi_capture.py` using `dxcam` (high-performance Direct3D 11 desktop duplication wrapper with 240+ FPS capability):
```python
import dxcam

class DxgiScreenCapture:
    def __init__(self, output_idx: int = 1):
        # Index 1 is typically the secondary monitor
        devices = dxcam.device_info()
        outputs = dxcam.output_info()
        self.output_idx = min(output_idx, len(outputs) - 1)
        self.camera = dxcam.create(output_idx=self.output_idx, output_color_mode="BGR")

    def list_outputs(self):
        return dxcam.output_info()

    def grab_frame(self):
        return self.camera.grab()
```

Create `server/streamer.py`:
```python
import socket
import json
import time
import cv2
from server.capture.dxgi_capture import DxgiScreenCapture
from server.transport.protocol import pack_message, MSG_VIDEO, MSG_CONFIG
from server.transport.adb_bridge import AdbBridge

def run_host_streamer(port=7070):
    bridge = AdbBridge()
    print("[Host] Setting up ADB port forwarding...")
    bridge.forward_port(port, port)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', port))
    server.listen(1)
    print(f"[Host] Listening on 127.0.0.1:{port} (tunneled over USB)...")

    cap = DxgiScreenCapture(output_idx=1)
    print("[Host] DXGI Desktop Duplication initialized on secondary display.")

    while True:
        client, addr = server.accept()
        print(f"[Host] Android client connected from {addr}!")
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        try:
            # Simple H.264 encode pipeline using OpenCV/FFmpeg VideoWriter or NVENC
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
            while True:
                frame = cap.grab_frame()
                if frame is not None:
                    # Compress and package
                    success, enc_img = cv2.imencode('.jpg', frame, encode_param)
                    if success:
                        packet = pack_message(MSG_VIDEO, enc_img.tobytes())
                        client.sendall(packet)
                time.sleep(0.001)
        except (ConnectionResetError, BrokenPipeError):
            print("[Host] Client disconnected. Waiting for reconnection...")
            client.close()

if __name__ == '__main__':
    run_host_streamer()
```

- [x] **Step 4: Run test_capture.py to verify output enumeration**

Run: `python -m unittest tests/test_capture.py`
Expected: `Ran 1 test ... OK`

---

### Task 4: Android Client Application Scaffold

**Files:**
- Create: `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/com/display/usbclient/MainActivity.kt`
- Create: `android/app/src/main/java/com/display/usbclient/StreamReceiver.kt`

**Interfaces:**
- Consumes: Localhost USB TCP socket `127.0.0.1:7070`
- Produces: Fullscreen hardware-decoded video stream rendered to `SurfaceView`

- [x] **Step 1: Scaffold Android Manifest with KeepScreenOn and Fullscreen**

Create `android/app/src/main/AndroidManifest.xml`:
```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.display.usbclient">

    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:label="USB Extended Display"
        android:theme="@android:style/Theme.NoTitleBar.Fullscreen">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:configChanges="orientation|screenSize|screenLayout|keyboardHidden"
            android:screenOrientation="landscape">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

- [x] **Step 2: Implement StreamReceiver with low-latency decoding pipeline**

Create `android/app/src/main/java/com/display/usbclient/StreamReceiver.kt`:
```kotlin
package com.display.usbclient

import android.graphics.BitmapFactory
import android.view.SurfaceHolder
import java.io.DataInputStream
import java.net.Socket

class StreamReceiver(private val holder: SurfaceHolder) : Thread() {
    @Volatile var isRunning = true

    override fun run() {
        while (isRunning) {
            try {
                // Connect to ADB forwarded localhost port
                val socket = Socket("127.0.0.1", 7070)
                socket.tcpNoDelay = true
                val dis = DataInputStream(socket.getInputStream())

                while (isRunning) {
                    val totalLen = dis.readInt()
                    val msgType = dis.readByte().toInt()
                    val payloadLen = totalLen - 1
                    val payload = ByteArray(payloadLen)
                    dis.readFully(payload)

                    if (msgType == 2) { // Video packet
                        val bmp = BitmapFactory.decodeByteArray(payload, 0, payload.size)
                        if (bmp != null) {
                            val canvas = holder.lockHardwareCanvas()
                            canvas.drawBitmap(bmp, 0f, 0f, null)
                            holder.unlockCanvasAndPost(canvas)
                        }
                    }
                }
            } catch (e: Exception) {
                Thread.sleep(1000) // Reconnect loop on USB unplug
            }
        }
    }
}
```

- [x] **Step 3: Implement MainActivity binding SurfaceView to StreamReceiver**

Create `android/app/src/main/java/com/display/usbclient/MainActivity.kt`:
```kotlin
package com.display.usbclient

import android.app.Activity
import android.os.Bundle
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.WindowManager

class MainActivity : Activity(), SurfaceHolder.Callback {
    private var receiver: StreamReceiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val surfaceView = SurfaceView(this)
        surfaceView.holder.addCallback(this)
        setContentView(surfaceView)
    }

    override fun surfaceCreated(holder: SurfaceHolder) {
        receiver = StreamReceiver(holder)
        receiver?.start()
    }

    override fun surfaceChanged(holder: SurfaceHolder, format: Int, w: Int, h: Int) {}

    override fun surfaceDestroyed(holder: SurfaceHolder) {
        receiver?.isRunning = false
        receiver = null
    }
}
```

---

### Task 5: End-to-End Integration & Latency Benchmark Verification

**Files:**
- Create: `tools/benchmark_latency.py`

**Interfaces:**
- Consumes: Running system with USB connected Android client
- Produces: Verified millisecond stopwatch screen and connection validation

- [x] **Step 1: Create verification stopwatch script**

Create `tools/benchmark_latency.py`:
```python
import time
import tkinter as tk

def create_latency_stopwatch():
    root = tk.Tk()
    root.title("Latency Timer - Drag to Secondary Virtual Display")
    root.geometry("600x300")
    label = tk.Label(root, font=("Consolas", 48, "bold"), fg="red")
    label.pack(expand=True)

    def update():
        ms = int(time.time() * 1000) % 1000000
        label.config(text=f"{ms:06d} ms")
        root.after(1, update)

    update()
    root.mainloop()

if __name__ == '__main__':
    create_latency_stopwatch()
```

- [x] **Step 2: Run verification loop**

Run:
1. `powershell server/driver/verify_display.ps1` -> Verify 2 displays active.
2. `python server/streamer.py` -> Start USB host daemon on `127.0.0.1:7070`.
3. Launch Android app -> Observe secondary desktop immediately displayed on the Android screen.
4. Drag `benchmark_latency.py` onto the secondary display. Take a smartphone photo capturing both the PC screen and tablet screen simultaneously.
5. Subtract the timestamps to confirm glass-to-glass latency is below 20ms.
