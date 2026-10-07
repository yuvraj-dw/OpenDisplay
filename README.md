# OpenDisplay 🖥️⚡📱

> **High-Performance USB Extended Monitor for Windows & Android**  
> Turn your Android tablet into a smooth, high-refresh-rate second monitor over USB with ultra-low latency, full touchscreen support, and automatic plug-and-play.

---

## ✨ Features

- **🚀 165Hz Ultra-High Refresh Rate:** Native support for 165Hz, 144Hz, 120Hz, and 60Hz virtual display modes.
- **🔌 Automatic USB Plug & Play:** Auto-detects USB connection. When you plug in your tablet, the display immediately activates. When you unplug it, Windows seamlessly returns to a single display.
- **🎯 Hardware Cursor Compositing:** Subpixel-accurate cursor rendering using native Win32 `DrawIconEx` alpha-blending with dynamic hotspot tracking.
- **👆 Interactive Touchscreen Support:** Tap and drag on your tablet screen to move the Windows cursor and click directly.
- **🔕 Silent System Tray Operation:** Runs quietly in the Windows notification area with zero console windows. Prompts for UAC once on startup and runs all driver operations silently without popups.
- **⚡ Zero Lag over USB:** Direct high-speed USB reverse tunnel via ADB (`tcp:7070` native streamer / `tcp:8080` hardware-accelerated web viewer).

---

## 🛠️ Quick Start

### 1. Requirements
- **Host PC:** Windows 10 or Windows 11 (64-bit)
- **Tablet:** Android 8.0+ tablet (e.g. Lenovo Tab M8, Samsung Galaxy Tab, etc.)
- **Connection:** Standard USB cable

### 2. Setup (1-Click)
1. Enable **Developer Options** and **USB Debugging** on your Android tablet.
2. Connect your tablet to your PC with a USB cable (allow USB debugging prompt if prompted on tablet).
3. Double-click **`OpenDisplay_Setup.bat`** (or `dist/OpenDisplay/OpenDisplay.exe`).

That's it! Your tablet will launch OpenDisplay and immediately become an extended monitor positioned at the bottom-left of your desktop.

---

## 🎮 System Tray Controls

OpenDisplay runs in your Windows System Tray (near the clock):
- **Right-Click Icon:**
  - View USB connection status
  - Open Tablet Viewer in browser (`http://127.0.0.1:8080`)
  - Exit & clean up virtual display
- **Double-Click Icon:** Opens the viewer stream in your browser.

---

## ⚙️ Manual Display Driver Controls

If you ever need to manually toggle the virtual display driver:
- **`Enable_Virtual_Display.bat`**: Enables the virtual display driver.
- **`Disable_Virtual_Display.bat`**: Disables the virtual display driver.

---

## 🏗️ Architecture

```
[Windows Host (OpenDisplay)]
     │
     ├─ VirtualDisplayDriver (MttVDD / IddSampleDriver - 165Hz)
     ├─ Screen Capture (DXGI Desktop Duplication & MSS)
     ├─ Subpixel Cursor Compositor (DrawIconEx / 32-bit DIB alpha)
     ├─ Stream Server (MJPEG / H.264 over tcp:8080 & tcp:7070)
     └─ Win32 System Tray & ADB USB Monitor Thread
             │  (USB Reverse Tunnel via ADB)
             ▼
[Android Client (OpenDisplay.apk)]
     └─ Hardware-accelerated WebView & Native Socket Client
```

---

## 📜 License

MIT License. Open-source and free for everyone.
