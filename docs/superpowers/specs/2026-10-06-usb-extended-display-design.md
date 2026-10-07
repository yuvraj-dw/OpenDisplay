# USB Extended Display System Design

## 1. Overview & Objective
This specification defines an ultra-low latency, hardware-accelerated wired USB extended display system between a Windows host and an Android tablet. The design replicates the display extension mechanics of SuperDisplay while omitting touch/stylus digitizer drivers, focusing entirely on maximum visual quality, 60/120 FPS performance, and sub-15ms latency over a direct USB cable connection.

---

## 2. Architecture & Components

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                WINDOWS HOST                                     │
│                                                                                 │
│   [ Windows DWM ]                                                               │
│          │                                                                      │
│          ▼ (DirectX SwapChain)                                                  │
│   [ IddSampleDriver / Virtual Display Driver ] (Secondary Monitor)               │
│          │                                                                      │
│          ▼ (DXGI Desktop Duplication: IDXGIOutputDuplication)                    │
│   [ Screen Capture Worker ] ──> D3D11 BGRA Texture                               │
│          │                                                                      │
│          ▼ (Direct3D 11 Video Processor / Shaders)                              │
│   [ Color Converter ] ──> NV12 Texture                                          │
│          │                                                                      │
│          ▼ (NVENC / QuickSync / AMF Hardware Encoder)                           │
│   [ Video Encoder Worker ] ──> Raw H.264 / HEVC NAL Units                       │
│          │                                                                      │
│          ▼ (TCP Socket on localhost:7070)                                       │
│   [ Host Stream Server ] ◄──[ adb forward tcp:7070 tcp:7070 ]                   │
└──────────┼──────────────────────────────────────────────────────────────────────┘
           │ Wired USB Cable (ADB Protocol)
┌──────────┼──────────────────────────────────────────────────────────────────────┐
│          ▼                                                                      │
│                               ANDROID CLIENT                                    │
│                                                                                 │
│   [ USB Client Socket ] (Connects to localhost:7070)                            │
│          │                                                                      │
│          ▼ (NAL Unit Extraction & Framing)                                      │
│   [ Stream Ingestion Worker ]                                                   │
│          │                                                                      │
│          ▼ (android.media.MediaCodec - Low Latency Mode)                        │
│   [ Hardware Decoder ]                                                          │
│          │                                                                      │
│          ▼ (Zero-Copy Native GPU Direct Render)                                 │
│   [ Fullscreen SurfaceView ] (1:1 Resolution, 60/120 FPS)                       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Component Breakdown

### A. Windows Virtual Display Adapter
* **Technology:** Indirect Display Driver (IddCx v1.4+) using the open-source community driver (`IddSampleDriver / Virtual Display Driver`).
* **Role:** Instantiates a virtual secondary monitor detected by Windows Desktop Window Manager (DWM).
* **Display Negotiation:** When the Android tablet connects, it sends its exact screen parameters (e.g., `2560x1600 @ 60Hz/120Hz`). The host configures the virtual monitor to match, providing crisp 1:1 pixel mapping with zero scaling artifacts.

### B. Windows Capture & GPU Encoding Pipeline
1. **Desktop Duplication:** Captures frames from the virtual display using `IDXGIOutputDuplication::AcquireNextFrame`. Captured frames stay directly in GPU VRAM as Direct3D 11 textures.
2. **Color Space Conversion:** Desktop surfaces (`DXGI_FORMAT_B8G8R8A8_UNORM`) are converted to `NV12` (YUV 4:2:0) directly on the GPU using `ID3D11VideoProcessor` or pixel shaders.
3. **Hardware Encoder:** Encodes NV12 surfaces into H.264 or HEVC using hardware MFT (Media Foundation Transform) or NVENC/AMF/QSV:
   * Low-latency profile: 0 B-frames, intra-refresh or periodic IDR, CBR (15–35 Mbps).
   * Frame rate: Synced with monitor refresh rate (60 FPS or 120 FPS).

### C. Wired USB Transport Layer
* **Transport:** TCP socket tunneled over USB using Android Debug Bridge (ADB).
* **Setup Command:** `adb forward tcp:7070 tcp:7070`.
* **Framing Protocol:**
  * **Header (4 bytes):** Payload length `uint32_t` (Big-Endian / Little-Endian).
  * **Flags (1 byte):** Frame type (`0x01` = Config/Handshake, `0x02` = Video NAL unit, `0x03` = Heartbeat).
  * **Payload:** Raw NAL unit data (SPS, PPS, IDR, non-IDR).

### D. Android Client Application
* **UI:** Single fullscreen `Activity` with `WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON` and immersive sticky fullscreen mode.
* **Decoder:** `android.media.MediaCodec` operating in low-latency synchronous/asynchronous mode configured with `KEY_LOW_LATENCY = 1` (Android 11+) and `KEY_OPERATING_RATE = 120`.
* **Renderer:** Outputs directly to `SurfaceView.holder.surface` for hardware composer zero-copy display.

---

## 4. Error Handling & Resilience
1. **USB Disconnect / Reconnect:**
   * Android client detects socket closure and initiates an exponential backoff retry loop to `localhost:7070`.
   * Windows host detects client disconnect, pauses screen capture/encoding to save GPU power, and waits for a new connection.
2. **Resolution Mismatch:**
   * Handshake packet explicitly declares width, height, and refresh rate before streaming begins.
3. **Framerate Drops / Starvation:**
   * Decoder skips non-reference frames or drops queued buffers if rendering falls behind real-time.

---

## 5. Verification Plan
1. **Virtual Monitor Setup Verification:** Verify virtual monitor is instantiated and shows up under `Settings > Display > Multiple displays > Extend these displays`.
2. **USB Tunnel Verification:** Test `adb forward tcp:7070 tcp:7070` and socket connectivity via test scripts.
3. **Encoding & Latency Verification:** Measure end-to-end glass-to-glass latency with a millisecond stopwatch displayed on the screen. Target latency: < 20ms over USB 2.0/3.0.
4. **Stress Testing:** Test hot-unplugging and replugging USB cable to verify automatic session resumption without crashing either side.
