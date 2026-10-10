# OpenDisplay

**OpenDisplay** turns any Android tablet into a high-refresh-rate, low-latency secondary monitor for Windows over a single USB cable. Engineered for hardware parity with commercial solutions like SuperDisplay, OpenDisplay delivers hardware-accelerated H.264 encoding and decoding with sub-millisecond decode latency.

---

## Key Highlights

- **Ultra-Low Latency Pipeline**:
  - Direct DXGI Desktop Duplication capture via **DXCAM** (~1.7ms capture time).
  - Hardware **NVIDIA NVENC** (or Intel QSV / MediaFoundation / CPU libx264 fallback) H.264 baseline encoding with `-tune ull` (Ultra Low Latency) and zero-copy memory transfers.
  - Native Android hardware **MediaCodec** decoding rendered directly to a zero-overhead **SurfaceView** (~0.67ms decode latency).
- **Dual Transport (AOAP + ADB)**:
  - **Android Open Accessory Protocol (AOAP)**: Custom signed WinUSB INF driver enables high-speed bulk USB transport **without requiring USB Debugging**.
  - **ADB Tunnel**: Automatic fallback to high-speed ADB reverse port forwarding (port 7070).
- **Zero-Touch Tablet Screen Wake**:
  - Automatically wakes the physical tablet display from deep sleep and bypasses swipe lockscreens upon USB connection.
- **Dynamic Non-Admin Display Lifecycle**:
  - Attaches the virtual monitor on connection and detaches it dynamically on exit or disconnect via standard user Win32 APIs (`ChangeDisplaySettingsEx`), snapping your desktop back instantly without UAC elevation prompts.
- **Windows Boot Autostart & System Tray Integration**:
  - Runs silently in the background with an interactive checkable System Tray menu (`[✓] Start with Windows`).
- **Touch & Mouse Input**:
  - Real-time touch and dragging on the tablet mapped accurately to desktop screen coordinates with hardware cursor compositing.

---

## Performance Profile (1280×800 @ 60 FPS)

| Metric | Measurement |
| :--- | :--- |
| **Capture Latency** | ~1.75 ms (DXCAM Direct GPU Staging) |
| **Encode Latency** | ~3.85 ms (NVIDIA NVENC ULL) |
| **Decode Latency** | ~0.67 ms (MediaCodec Hardware Surface) |
| **Total Display Latency** | **< 16 ms** (Real-time 60 FPS motion) |
| **Host CPU Usage** | **< 1%** (0% when tablet is disconnected) |
| **Host RAM Usage** | **~25 MB** |

---

## Requirements

- **Host PC**: Windows 10 or Windows 11 (64-bit).
- **Client Tablet**: Android 8.0 or newer.
- **Connection**: Standard USB-C or Micro-USB cable.

---

## Quick Start

### 1. Tablet Setup
1. Download and install **`OpenDisplay.apk`** from the [Latest Release](https://github.com/yuvraj-dw/OpenDisplay/releases).
2. Enable **USB Debugging** under Developer Options on your tablet (only needed if using ADB mode).

### 2. Windows PC Setup
1. Download **`OpenDisplay-v1.1.0-windows-x64.zip`** from [Releases](https://github.com/yuvraj-dw/OpenDisplay/releases) and extract it.
2. Run **`OpenDisplay_Setup.bat`** once. This:
   - Installs the Virtual Display Driver (UMDF).
   - Installs the WinUSB AOAP driver.
   - Registers OpenDisplay to start automatically with Windows.
3. Plug in your tablet via USB. OpenDisplay will detect the connection, turn on your tablet screen, and display your extended Windows desktop immediately.

---

## System Tray Controls

Right-click the OpenDisplay icon in the Windows notification area to:
- **Connection Status**: View active USB / TCP connection state.
- **Start with Windows**: Toggle automatic startup on Windows boot.
- **Web Viewer**: Launch browser fallback viewer (port 8080).
- **Exit**: Cleanly detaches the secondary monitor and exits.

---

## Repository Structure

```
├── android/              # Native Android client (Java/Kotlin, SurfaceView, MediaCodec)
├── server/               # Python streaming host
│   ├── capture/          # DXGI (DXCAM) and GDI desktop capture engines
│   ├── encoder/          # Hardware NVENC / libx264 low-latency video encoder
│   ├── transport/        # Native WinUSB AOAP transport & ADB bridge
│   ├── driver/           # Virtual Display Driver and WinUSB AOAP INF drivers
│   └── autostart.py      # Windows Registry autostart manager
├── tests/                # Automated unit and integration test suite (104 tests)
├── opendisplay_server.py # Core server orchestration & Win32 system tray
├── OpenDisplay_Setup.bat # One-click Windows setup launcher
└── build_apk.ps1         # Standalone Android APK build script
```

---

## Development & Testing

Run the full automated test suite:
```powershell
python -m unittest discover -s tests
```

Build standalone Windows binary:
```powershell
python -m PyInstaller OpenDisplay.spec --noconfirm
```

Build Android APK:
```powershell
powershell -ExecutionPolicy Bypass -File build_apk.ps1
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
