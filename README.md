# OpenDisplay

OpenDisplay turns an Android tablet into a second monitor for Windows over a USB cable. It creates a virtual display on Windows, captures the screen at up to 165Hz, and streams it to the tablet over an ADB reverse tunnel.

## Features

- High refresh rate support: 60Hz, 90Hz, 120Hz, 144Hz, and 165Hz (defaults to 165Hz on 1280x800).
- Automatic USB detection: detects when the tablet is plugged in and automatically starts streaming. Disabling or unplugging tears down the virtual display so Windows snaps back to your primary screen.
- Windows cursor compositing: draws the live Windows cursor on the stream using DrawIconEx with hotspot tracking.
- Touch input: tapping and dragging on the tablet moves the Windows mouse cursor and clicks.
- System tray app: runs in the background with an icon in the notification area. Requests admin permissions once on launch and manages display driver toggles silently.
- Low latency USB transport: runs over ADB reverse tunnel (port 7070 for native streaming, port 8080 for web viewer).

## Requirements

- Host PC: Windows 10 or 11 (64-bit)
- Tablet: Android 8.0 or newer with USB debugging enabled
- USB cable connecting the tablet to the PC

## How to use

1. Enable Developer Options and USB Debugging on your Android tablet.
2. Connect your tablet to the PC with a USB cable.
3. Run `OpenDisplay_Setup.bat` (or `dist\OpenDisplay\OpenDisplay.exe`).

The tablet will launch OpenDisplay and show the extended desktop. By default, the virtual monitor is placed to the bottom-left of your primary screen.

## Tray Controls

OpenDisplay sits in your system tray:
- Double-click the tray icon to open the viewer in your default browser.
- Right-click the tray icon to check connection status, open the web viewer, or exit cleanly.

## Manual Driver Controls

If you need to manually toggle the virtual display driver:
- `Enable_Virtual_Display.bat`: enables the virtual monitor device.
- `Disable_Virtual_Display.bat`: disables the virtual monitor device.

## Architecture

- Driver: IddSampleDriver fork (VirtualDisplayDriver) running in user-mode via UMDF.
- Capture: Desktop Duplication API (DXGI) and MSS with GDI fallback.
- Streamer: MJPEG over HTTP on port 8080 and raw packet stream on port 7070.
- Client: Android app with hardware-accelerated WebView and MediaCodec H.264 support.

## License

MIT
