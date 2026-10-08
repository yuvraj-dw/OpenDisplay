# SuperDisplay Native Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform OpenDisplay into an exact copy of SuperDisplay's low-latency hardware architecture using native Android `SurfaceView` + `MediaCodec` (H.264) connected to Windows GPU hardware encoding on TCP port 7070.

**Architecture:** The Windows server captures Display 1 via DXGI Desktop Duplication and encodes frames with GPU-accelerated H.264 (`h264_nvenc` / `h264_qsv` / `libx264` zero-latency) into framed NAL packets over TCP port 7070. The Android client displays the stream via a full-screen native `SurfaceView` wired directly to hardware `MediaCodec` for sub-2ms decoding with zero memory copying and near-zero CPU usage.

**Tech Stack:** Java (Android SDK, `SurfaceView`, `MediaCodec`), Python (DirectX DXGI capture, PyWin32, FFmpeg NVENC/QSV, Winsock TCP streaming), ADB reverse tunnel.

## Global Constraints
- Target tablet resolution: 1280x800.
- Target frame rate: 60 FPS.
- Target end-to-end latency: < 15ms over USB.
- Host runs without requiring Administrator elevation prompts during streaming or shutdown.
- All code must pass unit tests and build without compiler warnings.

---

### Task 1: Android Client Native SurfaceView & H264Decoder Pipeline

**Files:**
- Modify: `android/app/src/main/java/com/display/usbclient/MainActivity.java`
- Modify: `android/app/src/main/java/com/display/usbclient/H264Decoder.java`
- Modify: `android/app/src/main/java/com/display/usbclient/StreamReceiver.java`
- Test: `build_apk.ps1`

**Interfaces:**
- Consumes: Surface lifecycle from `android.view.SurfaceHolder.Callback`
- Produces: `StreamReceiver` receiving NAL units from `127.0.0.1:7070` and feeding `H264Decoder.decodeFrame()`

- [ ] **Step 1: Update H264Decoder for robust low-latency decoding**
Ensure `H264Decoder.java` handles `KEY_LOW_LATENCY = 1`, uses `MediaCodec.createDecoderByType("video/avc")`, and properly drains decoded buffers to surface with `releaseOutputBuffer(outputIndex, true)`.

- [ ] **Step 2: Update StreamReceiver for packet unmarshaling and auto-reconnect**
Ensure `StreamReceiver.java` reads `[4-byte int length][1-byte msgType][payload]` and passes `MSG_VIDEO` packets to `H264Decoder`.

- [ ] **Step 3: Update MainActivity.java to use native SurfaceView**
Replace `WebView` completely with a full-screen `SurfaceView`. Wire `SurfaceHolder.Callback` to initialize `H264Decoder` and start `StreamReceiver` on `surfaceCreated`, and cleanly stop on `surfaceDestroyed`.

- [ ] **Step 4: Verify APK compilation**
Run `powershell -ExecutionPolicy Bypass -File build_apk.ps1` to ensure `OpenDisplay.apk` compiles cleanly with the new `SurfaceView` architecture.

- [ ] **Step 5: Commit**
```bash
git add android/app/src/main/java/com/display/usbclient/ build_apk.ps1
git commit -m "feat(android): replace webview with native SurfaceView and hardware MediaCodec"
```

---

### Task 2: Android Touch & Stylus Input Pipeline

**Files:**
- Modify: `android/app/src/main/java/com/display/usbclient/MainActivity.java`
- Modify: `android/app/src/main/java/com/display/usbclient/StreamReceiver.java`
- Test: `build_apk.ps1`

**Interfaces:**
- Consumes: `View.OnTouchListener` events on `SurfaceView`
- Produces: `StreamReceiver.sendTouch(action, normX, normY)` transmitting binary/text messages `m:action:x:y\n` to host socket.

- [ ] **Step 1: Add socket writing capability to StreamReceiver**
Add `sendTouch(String action, float normX, float normY)` to `StreamReceiver.java` using a background output stream or queue to avoid blocking the main UI thread.

- [ ] **Step 2: Attach OnTouchListener to SurfaceView in MainActivity**
Capture `ACTION_DOWN`, `ACTION_MOVE`, and `ACTION_UP`. Compute normalized coordinates `[0.0, 1.0]` relative to the `SurfaceView` bounds, and call `streamReceiver.sendTouch(...)`.

- [ ] **Step 3: Verify APK compilation**
Run `powershell -ExecutionPolicy Bypass -File build_apk.ps1` and verify the signed APK builds successfully.

- [ ] **Step 4: Commit**
```bash
git add android/app/src/main/java/com/display/usbclient/MainActivity.java android/app/src/main/java/com/display/usbclient/StreamReceiver.java
git commit -m "feat(android): add low-latency touch and stylus event streaming"
```

---

### Task 3: Windows Host Native H.264 Streamer Pipeline

**Files:**
- Modify: `server/encoder/hw_encoder.py`
- Modify: `server/streamer.py`
- Modify: `opendisplay_server.py`
- Test: `tests/test_streamer.py`, `tests/test_hw_encoder.py`

**Interfaces:**
- Consumes: `DxgiScreenCapture.capture_frame(display_idx)`
- Produces: TCP port 7070 binary stream sending `[length][MSG_VIDEO][H.264 NAL bytes]`

- [ ] **Step 1: Configure HardwareEncoder for zero-latency NVENC H.264**
In `server/encoder/hw_encoder.py`, ensure `h264_nvenc` and `libx264` use:
`-preset p1 -tune ll -zerolatency 1 -bf 0 -g 60 -x264-params repeat-headers=1:keyint=60` and CBR 6 Mbps bitrate.

- [ ] **Step 2: Update Streamer to broadcast H.264 NAL frames over port 7070**
In `server/streamer.py`, ensure the capture loop pushes frames through `HardwareEncoder(codec="auto")` and broadcasts them to all connected Android clients on port 7070.

- [ ] **Step 3: Integrate native Streamer into opendisplay_server.py**
In `opendisplay_server.py`, initialize and start `Streamer(port=STREAM_PORT, display_idx=1, fps=60)` as the primary streaming service.

- [ ] **Step 4: Run unit tests**
Run `python -m unittest discover -s tests` to verify encoder and streaming tests pass.

- [ ] **Step 5: Commit**
```bash
git add server/encoder/hw_encoder.py server/streamer.py opendisplay_server.py
git commit -m "feat(server): enable zero-latency GPU NVENC H.264 streaming on port 7070"
```

---

### Task 4: Windows Touch & Mouse Event Processing

**Files:**
- Modify: `server/streamer.py`
- Modify: `opendisplay_server.py`
- Test: `tests/test_streamer.py`

**Interfaces:**
- Consumes: Client socket input `m:action:x:y\n`
- Produces: Win32 `ctypes.windll.user32.SetCursorPos` and `mouse_event` dispatches on Display 1.

- [ ] **Step 1: Implement client socket reader in Streamer**
In `server/streamer.py`, spawn a reader thread for each connected client that listens for incoming `m:action:x:y` packets.

- [ ] **Step 2: Map normalized coordinates to Display 1 virtual desktop coordinates**
Retrieve Display 1 geometry (`left, top, width, height`) and map `(normX, normY)` to `(int(left + normX * width), int(top + normY * height))`.

- [ ] **Step 3: Dispatch mouse events via user32**
Call `SetCursorPos(x, y)` and `mouse_event(MOUSEEVENTF_LEFTDOWN)` / `mouse_event(MOUSEEVENTF_LEFTUP)`.

- [ ] **Step 4: Run unit tests**
Run `python -m unittest discover -s tests` to verify streamer input handling.

- [ ] **Step 5: Commit**
```bash
git add server/streamer.py opendisplay_server.py
git commit -m "feat(server): handle client touch and mouse events over stream socket"
```

---

### Task 5: End-to-End Build, Deploy, and Verification

**Files:**
- Modify: `OpenDisplay_Setup.bat`
- Build: `OpenDisplay.exe`, `OpenDisplay.apk`
- Test: Live test on connected Lenovo Tab M8

**Interfaces:**
- Consumes: Complete host and client binaries
- Produces: Verified 60 FPS low-latency display mirroring on tablet

- [ ] **Step 1: Update OpenDisplay_Setup.bat**
Ensure `OpenDisplay_Setup.bat` launches `OpenDisplay.exe` in background, establishes `adb reverse tcp:7070 tcp:7070`, and launches `com.display.usbclient/.MainActivity`.

- [ ] **Step 2: Build OpenDisplay.apk and install on tablet**
Execute `powershell -ExecutionPolicy Bypass -File build_apk.ps1` and install the APK via `adb install -r -d OpenDisplay.apk`.

- [ ] **Step 3: Compile standalone OpenDisplay.exe**
Run PyInstaller to create the updated `dist\OpenDisplay\OpenDisplay.exe` without `--uac-admin`.

- [ ] **Step 4: Live verification on Lenovo Tab M8**
Start OpenDisplay, verify `adb logcat` shows hardware `MediaCodec` decoding at 60 FPS, and verify smooth cursor movement and zero thermal throttling.

- [ ] **Step 5: Commit and release sync**
Commit all final changes and push to GitHub repository.
