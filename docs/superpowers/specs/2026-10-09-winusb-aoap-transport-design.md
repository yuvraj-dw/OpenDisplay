# OpenDisplay: Full Driver-Level AOAP & WinUSB Transport Design

## 1. Executive Summary & Goals
OpenDisplay v1.1.0 achieved parity with SuperDisplay's video decoding and encoding pipeline (native `SurfaceView` + hardware `MediaCodec` + GPU `h264_nvenc` + zero elevation). 

This design specifies the remaining hardware transport layer: **Full Driver-Level Android Open Accessory Protocol (AOAP) and Windows WinUSB transport**.

### Key Objectives
1. **Direct USB Bulk Transport**: Replace TCP network stack with direct USB bulk pipes (`WinUSB.sys` on Windows, `UsbAccessory` on Android) for lower latency, zero packet loss, and zero socket buffer overhead.
2. **True Plug-and-Play (Zero ADB Requirement)**: Support running without enabling Android USB Debugging or ADB reverse tunnels. When the USB cable connects, the Android device enters accessory mode and automatically launches OpenDisplay.
3. **Seamless Failover Pool**: Retain high-speed TCP streaming on port 7070 as an automatic fallback when running over Wi-Fi or when the AOAP driver is not yet registered.
4. **Clean Driver Integration**: Provide `opendisplay_aoap.inf` binding Microsoft's native `WinUSB.sys` to Google Accessory mode hardware IDs (`18D1:2D00` and `18D1:2D01`) via Windows `pnputil` / `devcon`.

---

## 2. Architecture & Components

```
                        UNIFIED TRANSPORT PIPELINE
                        
    ┌───────────────────────── WINDOWS HOST ─────────────────────────┐
    │                                                                │
    │   DXGI Desktop Capture (1280x800 @ 165Hz)                      │
    │        │                                                       │
    │        ▼                                                       │
    │   GPU NVENC H.264 Encoder (h264_nvenc / QSV / libx264)         │
    │        │                                                       │
    │        ▼                                                       │
    │   Packet Framer: [4B len][1B type][payload]                   │
    │        │                                                       │
    │        ├──► WinUsbTransport (Bulk Endpoint 0x02 OUT) ─────────┐│ (Direct USB Bulk)
    │        │                                                       ││
    │        └──► Streamer (TCP Server tcp:7070) ──────────────────┐ ││ (Network Fallback)
    └──────────────────────────────────────────────────────────────┼─┼┘
                                                                   │ │
    ┌───────────────────────── ANDROID TABLET ─────────────────────┼─┼┐
    │                                                              │ ││
    │        ┌─── StreamReceiver (tcp:7070) ◄──────────────────────┘ ││
    │        │                                                       ││
    │        └─── UsbAccessory Receiver (AOAP Bulk IN) ◄─────────────┘│
    │                 │                                               │
    │                 ▼                                               │
    │            NAL Parser                                           │
    │                 │                                               │
    │                 ▼                                               │
    │            Hardware MediaCodec (OMX.MTK.VIDEO.DECODER.AVC)      │
    │                 │                                               │
    │                 ▼ (Zero-Copy Direct Render)                     │
    │            SurfaceView (1280x800 @ 60+ FPS)                     │
    │                 │                                               │
    │           (Touch Input: m:action:normX:normY\n)                 │
    │                 │                                               │
    │                 ▼                                               │
    │            AOAP Bulk OUT / TCP Out ──► Host Cursor Injection    │
    └─────────────────────────────────────────────────────────────────┘
```

---

## 3. Windows Driver & Host Transport Engine

### 3.1 Driver Specification (`server/driver/aoap_bin/opendisplay_aoap.inf`)
- **Driver Class**: Standard Microsoft `USBDevice` (`ClassGUID = {88BAE032-5A81-49f0-BC3D-A4FF138216D6}`)
- **Target Hardware IDs**:
  - `USB\VID_18D1&PID_2D00`: Android Accessory Mode (standalone)
  - `USB\VID_18D1&PID_2D01`: Android Accessory + ADB composite mode
  - `USB\VID_18D1&PID_2D01&MI_00`: Android Accessory interface when composite
- **Kernel Service**: Standard Windows built-in `WinUSB.sys` (`Include=winusb.inf`, `Needs=WINUSB.NT`). No unsigned or third-party kernel drivers required.
- **Device Interface GUID**: Custom UUID `{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}` registered under `DeviceInterfaceGUIDs`.
- **Installation Mechanism**:
  - `pnputil.exe /add-driver opendisplay_aoap.inf /install`
  - Integrated into `install_aoap_driver.bat` and `OpenDisplay_Setup.bat`.

### 3.2 Native Windows WinUSB Transport (`server/transport/winusb_transport.py`)
- **API Boundary**: Pure Python via `ctypes` calling `winusb.dll` and `setupapi.dll` natively. Zero external C compilation or third-party DLL dependencies.
- **Device Discovery**:
  - Calls `SetupDiGetClassDevsW` with `{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}` (`DIGCF_PRESENT | DIGCF_DEVICEINTERFACE`).
  - Calls `SetupDiEnumDeviceInterfaces` and `SetupDiGetDeviceInterfaceDetailW` to obtain the system device symbolic link path.
  - Opens file handle via `CreateFileW` with `GENERIC_READ | GENERIC_WRITE`, `FILE_SHARE_READ | FILE_SHARE_WRITE`, `OPEN_EXISTING`, and `FILE_FLAG_OVERLAPPED`.
- **Interface & Pipe Configuration**:
  - Initializes WinUSB handle via `WinUsb_Initialize`.
  - Queries USB interface descriptor via `WinUsb_QueryInterfaceSettings`.
  - Enumerates pipes with `WinUsb_QueryPipe`:
    - Endpoint `0x02` (Bulk OUT): Used for host-to-device streaming (Video NALs, Config, Heartbeats).
    - Endpoint `0x81` (Bulk IN): Used for device-to-host input (Touch, Stylus events).
  - Pipe Policies:
    - Sets `RAW_IO = True` on Bulk OUT pipe to bypass intermediate buffering and achieve zero-copy DMA transfer.
    - Sets `PIPE_TRANSFER_TIMEOUT = 1000ms`.
- **AOA Protocol Initiation**:
  - Scans connected USB devices. When an Android device in standard mode (e.g. MTP or ADB) is detected, the host sends the AOA 2.0 handshake control transfers to Endpoint 0:
    - **Request 51 (`ACCESSORY_GET_PROTOCOL`)**: Reads 2-byte protocol version (expects version >= 1).
    - **Request 52 (`ACCESSORY_SEND_STRING`)**: Writes 6 UTF-8 null-terminated metadata strings:
      - String 0 (Manufacturer): `OpenDisplay`
      - String 1 (Model): `OpenDisplay`
      - String 2 (Description): `OpenDisplay High-Speed USB Display`
      - String 3 (Version): `1.1`
      - String 4 (URI): `https://github.com/yuvraj-dw/OpenDisplay`
      - String 5 (Serial): `000000001`
    - **Request 53 (`ACCESSORY_START`)**: Directs Android device to switch into USB Accessory mode.
  - The Android device re-enumerates on the USB bus as `VID_18D1&PID_2D00` or `VID_18D1&PID_2D01`, triggering Windows to bind `opendisplay_aoap.inf`.

---

## 4. Android UsbAccessory & Auto-Launch Pipeline

### 4.1 Accessory Filter (`android/app/src/main/res/xml/accessory_filter.xml`)
Declares exact matching attributes matching Request 52 strings:
```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <usb-accessory
        manufacturer="OpenDisplay"
        model="OpenDisplay"
        version="1.1" />
</resources>
```

### 4.2 Manifest Declaration (`android/app/src/main/AndroidManifest.xml`)
- Declares optional accessory feature:
  ```xml
  <uses-feature android:name="android.hardware.usb.accessory" android:required="false" />
  ```
- Registers accessory intent filter on `MainActivity`:
  ```xml
  <intent-filter>
      <action android:name="android.hardware.usb.action.USB_ACCESSORY_ATTACHED" />
  </intent-filter>
  <meta-data
      android:name="android.hardware.usb.action.USB_ACCESSORY_ATTACHED"
      android:resource="@xml/accessory_filter" />
  ```

### 4.3 Android Transport Pipeline (`StreamReceiver.java` / `MainActivity.java`)
- **Attachment & Acquisition**:
  - When Android attaches an accessory matching the filter, it sends `USB_ACCESSORY_ATTACHED` intent with `UsbManager.EXTRA_ACCESSORY`.
  - In `MainActivity.onResume()` / `onNewIntent()`:
    - Retrieve `UsbAccessory accessory = intent.getParcelableExtra(UsbManager.EXTRA_ACCESSORY)` (or `usbManager.getAccessoryList()[0]`).
    - If present, instantiate `StreamReceiver` in AOAP mode passing the `UsbAccessory`.
    - If null, instantiate `StreamReceiver` in TCP mode connecting to `127.0.0.1:7070`.
- **I/O Streaming**:
  - Opens `ParcelFileDescriptor pfd = usbManager.openAccessory(accessory)`.
  - Obtains `FileDescriptor fd = pfd.getFileDescriptor()`.
  - Stream Reader: `DataInputStream(new BufferedInputStream(new FileInputStream(fd), 64 * 1024))`.
  - Stream Writer: `FileOutputStream(fd)` protected by `outputLock`.
  - Unmarshals standard binary frames (`[4B totalLen][1B msgType][payload]`).
  - Passes NAL units to `H264Decoder` for direct rendering to `SurfaceView`.
  - Offloads touch coordinate events (`m:action:normX:normY\n`) to `FileOutputStream` via single-thread executor with `DiscardOldestPolicy`.

---

## 5. Wire Protocol & Wire Framing

The wire protocol is identical across both WinUSB bulk transfer and TCP socket transport:

```
┌────────────────────────────────┬──────────────┬───────────────────────────────┐
│ Total Length (4 Bytes Big End) │ Type (1 Byte)│ Payload (Total Length - 1 B)  │
└────────────────────────────────┴──────────────┴───────────────────────────────┘
```

- **Type `0x01` (`MSG_CONFIG`)**:
  - Payload: UTF-8 JSON `{"width": 1280, "height": 800, "fps": 60}`
- **Type `0x02` (`MSG_VIDEO`)**:
  - Payload: Binary H.264 Annex B NAL units (`0x00 00 00 01` delimiters). Includes SPS, PPS, IDR, non-IDR slices.
- **Type `0x03` (`MSG_HEARTBEAT`)**:
  - Payload: 8-byte millisecond timestamp for RTT tracking.
- **Type `0x04` (`MSG_INPUT`)**:
  - Payload: UTF-8 string formatted as `m:<action>:<normX>:<normY>\n`
  - Actions: `down`, `move`, `up`.

---

## 6. Host Coordination & Auto-Failover

In `opendisplay_server.py`:
1. Server initializes both the `WinUsbTransport` subsystem and the `Streamer` TCP server (`0.0.0.0:7070`).
2. When a WinUSB accessory device is opened, the host marks USB as the primary transport:
   - GPU encoded H.264 packets are dispatched directly to the WinUSB bulk OUT pipe.
   - Incoming touch messages from the WinUSB bulk IN pipe are passed to Win32 `SetCursorPos` and `mouse_event`.
3. If WinUSB is disconnected or not present, incoming TCP connections on `7070` are actively served.
4. If a tablet connects over ADB, the server automatically sets up reverse tunnels `tcp:7070` as before.

---

## 7. Verification & Testing Strategy

1. **Unit Tests**:
   - `tests/test_winusb_transport.py`: Mock `setupapi.dll` and `winusb.dll` device enumeration, packet writing, and touch packet reading.
   - `tests/test_aoap_framing.py`: Verify identical packet framing on both byte streams and sockets.
2. **Device Hardware Verification**:
   - Register `opendisplay_aoap.inf` using `pnputil.exe`.
   - Connect Lenovo Tab M8 (TB-8505F).
   - Verify device switches into `VID_18D1&PID_2D00` / `PID_2D01`.
   - Verify `UsbAccessory` intent triggers automatic app startup on the tablet.
   - Measure decode FPS and RTT latency via `BufferQueueProducer` and packet timestamps.
