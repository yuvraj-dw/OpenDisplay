# OpenDisplay Native Low-Latency Architecture Design Spec

**Date:** 2026-10-08  
**Topic:** SuperDisplay Parity — Native H.264 Hardware Pipeline  
**Target Device:** Lenovo Tab M8 (TB-8505F, 1280x800, MediaTek Helio A22)  
**Host System:** Windows 10/11 x64 (with NVIDIA RTX 4050 / Intel UHD Graphics)  

---

## 1. Problem Statement & Background

OpenDisplay currently relies on an Android `WebView` rendering MJPEG over HTTP/WebSocket. 
While functionally complete, testing on the Lenovo Tab M8 revealed:
1. **CPU Saturation:** The MediaTek MT6761 (Helio A22, 4x Cortex-A53 @ 2.0 GHz) decodes full-resolution 1280x800 JPEGs in software within Chromium's single-threaded image decoder. Each frame requires 35–45ms of CPU decode time, physically limiting frame rates to ~22–26 FPS and triggering thermal throttling down to 2–5 FPS.
2. **Bandwidth Overhead:** MJPEG streams require 30–50 Mbps of bandwidth over the USB ADB tunnel, leading to bufferbloat and 200–500ms of lag.

### SuperDisplay Evidence
Reverse-engineering SuperDisplay (`SuperDisplay.apk` and `MirrorService.exe` via REA) proved:
- **No WebView:** SuperDisplay uses a native `android.view.SurfaceView`.
- **Zero-Copy Hardware Decoding:** Android's native `MediaCodec` (`video/avc`) is bound directly to the `SurfaceView`'s `Surface`, decoding frames in hardware in **< 2ms** at **~2% CPU usage**.
- **GPU Hardware Encoding:** Windows host captures the desktop via DXGI Desktop Duplication and encodes directly on the GPU using NVIDIA NVENC / Media Foundation into low-latency H.264 (4–6 Mbps total bandwidth, ~1.5ms encode time).
- **Packet Transport:** Dedicated binary framing over TCP (`TCP_NODELAY`, 512KB buffer) and decoupled input.

---

## 2. Architecture & System Flow

```
[ Windows Host ]
  Desktop Duplication (DXGI) [1280x800 @ 165Hz]
       │ (DirectX Texture)
       ▼
  HardwareEncoder (FFmpeg / NVENC / QSV / libx264 zerolatency)
       │ (H.264 NAL Units: SPS, PPS, IDR, P-frames)
       ▼
  Streamer Server (TCP port 7070, TCP_NODELAY = 1)
       │
═══════╪═════════════════════════════════════════════════════ USB ADB Reverse Tunnel (tcp:7070)
       ▼
[ Android Tablet ]
  StreamReceiver (TCP Socket Client @ 127.0.0.1:7070)
       │ (Binary Packets: [4B len][1B type][payload])
       ▼
  H264Decoder (MediaCodec API: "video/avc")
       │ (Hardware Decoded Frames: < 2ms)
       ▼
  SurfaceView / Surface (Hardware Overlay / SurfaceFlinger)
```

---

## 3. Detailed Component Specifications

### 3.1 Android Client (`MainActivity.java`)
- **Root View:** Replace `WebView` with `android.view.SurfaceView`.
- **Surface Lifecycle:** Implement `SurfaceHolder.Callback`:
  - `surfaceCreated(SurfaceHolder holder)`: Pass `holder.getSurface()` to `H264Decoder.configure()`.
  - `surfaceChanged(...)`: Update decoder dimensions (1280x800).
  - `surfaceDestroyed(...)`: Release or pause decoder surface.
- **Decoder (`H264Decoder.java`)**:
  - `MediaCodec.createDecoderByType("video/avc")`.
  - `MediaFormat.createVideoFormat("video/avc", 1280, 800)`.
  - Set `MediaFormat.KEY_LOW_LATENCY = 1` for Android 11+ and `KEY_OPERATING_RATE = 165`.
  - Bound directly to `Surface`: decoded frames are automatically sent to hardware display output upon `releaseOutputBuffer(index, true)`.
- **Worker Receiver (`StreamReceiver.java`)**:
  - Connects to `127.0.0.1:7070` with `TCP_NODELAY = true` and 512KB socket buffer.
  - Automatically reconnects upon socket close or USB disconnect.
  - Passes incoming NAL units to `decoder.decodeFrame(payload)`.
- **Touch & Stylus Input**:
  - `SurfaceView.setOnTouchListener()` intercepts touch down, move, and up.
  - Normalizes touch coordinates to `[0.0, 1.0]`.
  - Sends binary/text input packet back through the open socket to Windows host.

### 3.2 Windows Host Streamer (`server/streamer.py` & `opendisplay_server.py`)
- **Port:** Primary binary streaming on `tcp:7070` (retaining HTTP port 8080 as optional web viewer).
- **Encoder Pipeline (`HardwareEncoder`)**:
  - Codec: H.264 via `h264_nvenc` (NVIDIA RTX 4050), fallback to `h264_qsv` (Intel UHD) or `libx264`.
  - Tuning: `-preset p1 -tune ll -zerolatency 1 -bf 0` (NVENC) or `-preset ultrafast -tune zerolatency -bf 0` (libx264).
  - Bitrate: 6000k (6 Mbps CBR), `maxrate 6000k`, `bufsize 1M`.
  - Keyframes: GOP size = 60, `repeat-headers=1` so SPS/PPS parameter sets are sent on every keyframe, allowing instantaneous client reconnection without black screens.
- **Capture Integration**:
  - `DxgiScreenCapture` captures Display 1 (1280x800).
  - Encoded H.264 NAL units are emitted and packed into `pack_message(MSG_VIDEO, nal_bytes)`.
- **Socket Options**:
  - `socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)`
  - `socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)`
- **Input Handling**:
  - Server reads client touch packets from the same connection.
  - Maps normalized coordinates `(x, y)` to Windows Display 1 virtual desktop coordinates `(left + x*w, top + y*h)`.
  - Dispatches via `SetCursorPos` and `mouse_event`.

---

## 4. Binary Wire Protocol Specification

Every packet over port 7070 follows the framed structure:
- **Total Length** (4 bytes, Big-Endian integer): `len(payload) + 1`
- **Message Type** (1 byte):
  - `0x01` (`MSG_CONFIG`): JSON configuration `{"width": 1280, "height": 800, "fps": 60}`
  - `0x02` (`MSG_VIDEO`): Raw H.264 video NAL unit stream
  - `0x03` (`MSG_HEARTBEAT`): Keepalive ping
  - `0x04` (`MSG_INPUT`): Touch/mouse event `down|move|up x y`
- **Payload** (`N` bytes): Raw packet data.

---

## 5. Build & Packaging Plan

1. **Android Client (`build_apk.ps1`)**:
   - Compile Java classes (`MainActivity.java`, `H264Decoder.java`, `StreamReceiver.java`).
   - Package with D8 dexer and AAPT2.
   - Sign with debug keystore and install to tablet via `adb install -r -d OpenDisplay.apk`.
2. **Windows Server (`opendisplay_server.py`)**:
   - Integrate `Streamer` on `tcp:7070` as default streaming backend.
   - Ensure PyInstaller builds clean standalone `OpenDisplay.exe`.

---

## 6. Verification & Success Criteria

1. **Latency:** End-to-end motion-to-photon latency < 15ms over USB.
2. **Frame Rate:** Sustained 60 FPS without dropping frames over 10+ minutes.
3. **CPU Usage:** Lenovo Tab M8 CPU usage remains under 5% during active streaming.
4. **Thermal Stability:** Zero thermal throttling or memory growth on tablet.
5. **Recovery:** Unplugging and replugging USB cable resumes stream within 1 second.
