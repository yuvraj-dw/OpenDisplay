import os
import sys
import time
import socket
import threading
import subprocess
import shutil
import atexit
import signal
import ctypes
import webbrowser
import base64
import hashlib
import struct
import select
import numpy as np
from ctypes import wintypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import win32api
import win32con
import win32gui

from server.capture.dxgi_capture import DxgiScreenCapture
from server.encoder.hw_encoder import HardwareEncoder
from server.streamer import Streamer

# Enable Per-Monitor DPI Awareness v2 at earliest possible entry point
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Safe null guards for windowed / no-console mode
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# Hide console window if launched from cmd/batch
try:
    _hwnd_console = win32gui.GetConsoleWindow()
    if _hwnd_console:
        win32gui.ShowWindow(_hwnd_console, win32con.SW_HIDE)
except Exception:
    pass

PORT = 8080
STREAM_PORT = 7070

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def ensure_elevated():
    """Request administrative elevation once on launch to prevent repeated UAC prompts."""
    if not is_admin():
        try:
            if getattr(sys, 'frozen', False):
                exe = sys.executable
                args = " ".join([f'"{a}"' for a in sys.argv[1:]])
            else:
                exe = sys.executable
                args = f'"{os.path.abspath(__file__)}" ' + " ".join([f'"{a}"' for a in sys.argv[1:]])
            ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
            sys.exit(0)
        except Exception:
            pass

def _find_devcon():
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "devcon.exe"),
        os.path.join(os.path.dirname(sys.executable), "_internal", "devcon.exe"),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "server", "driver", "vdd_bin", "VirtualDisplayDriver", "devcon.exe")),
        os.path.join(os.getcwd(), "server", "driver", "vdd_bin", "VirtualDisplayDriver", "devcon.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return shutil.which("devcon.exe") or shutil.which("devcon")

def _run_devcon(action):
    """Executes devcon commands silently without repeated UAC popups."""
    devcon = _find_devcon()
    if not devcon:
        return False
    try:
        if is_admin():
            res = subprocess.run(
                [devcon, action, "Root\\MttVDD"],
                capture_output=True,
                text=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=5
            )
            return res.returncode == 0
        else:
            ps_cmd = f"Start-Process '{devcon}' -ArgumentList '{action} Root\\MttVDD' -Verb RunAs -WindowStyle Hidden -Wait"
            subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, timeout=5)
            return True
    except Exception as e:
        print(f"[OpenDisplay] Devcon {action} error: {e}")
        return False

def enable_virtual_display():
    devcon = _find_devcon()
    if devcon:
        try:
            stat = subprocess.run([devcon, "status", "Root\\MttVDD"], capture_output=True, text=True, creationflags=0x08000000, timeout=3)
            if "running" not in stat.stdout.lower():
                print("[OpenDisplay] Enabling virtual extended monitor...")
                _run_devcon("enable")
                time.sleep(1.0)
        except Exception:
            pass
    align_secondary_display_bottom_left(refresh_rate=165)

def align_secondary_display_bottom_left(refresh_rate=165):
    """Ensure Windows places the secondary monitor in the bottom-left at 165Hz."""
    try:
        primary_height = 1080
        for i in range(40):
            try:
                dev = win32api.EnumDisplayDevices(None, i)
                if (dev.StateFlags & win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP) and (dev.StateFlags & win32con.DISPLAY_DEVICE_PRIMARY_DEVICE):
                    dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    primary_height = dm.PelsHeight
                    break
            except Exception:
                pass

        for i in range(40):
            try:
                dev = win32api.EnumDisplayDevices(None, i)
                if (dev.StateFlags & win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP) and not (dev.StateFlags & win32con.DISPLAY_DEVICE_PRIMARY_DEVICE):
                    dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    target_x = -dm.PelsWidth
                    target_y = primary_height - dm.PelsHeight
                    changed = False
                    if dm.Position_x != target_x or dm.Position_y != target_y:
                        dm.Position_x = target_x
                        dm.Position_y = target_y
                        dm.Fields |= win32con.DM_POSITION
                        changed = True
                    if dm.DisplayFrequency != refresh_rate:
                        dm.DisplayFrequency = refresh_rate
                        dm.Fields |= win32con.DM_DISPLAYFREQUENCY
                        changed = True
                    if changed:
                        win32api.ChangeDisplaySettingsEx(dev.DeviceName, dm, win32con.CDS_UPDATEREGISTRY)
                        win32api.ChangeDisplaySettingsEx(None, None, 0)
                        print(f"[OpenDisplay] Configured display at bottom-left ({target_x}, {target_y}) @ {refresh_rate}Hz")
            except Exception:
                pass
    except Exception:
        pass

def disable_virtual_display():
    """Terminates the virtual display when OpenDisplay stops, returning Windows to a single monitor."""
    print("[OpenDisplay] Disconnecting virtual extended monitor...")
    _run_devcon("disable")
    print("[OpenDisplay] Virtual monitor disconnected successfully.")

# Register exit hooks so the display unplugs when the process closes
atexit.register(disable_virtual_display)

try:
    PHANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    def _console_ctrl_handler(dwCtrlType):
        disable_virtual_display()
        return False
    _ctrl_func = PHANDLER_ROUTINE(_console_ctrl_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_ctrl_func, True)
except Exception:
    pass

try:
    signal.signal(signal.SIGINT, lambda s, f: (disable_virtual_display(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda s, f: (disable_virtual_display(), sys.exit(0)))
except Exception:
    pass

HTML_VIEWER = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>OpenDisplay Extended Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body, html { width: 100%; height: 100%; background: #000; overflow: hidden; touch-action: none; }
        #canvas { width: 100vw; height: 100vh; object-fit: fill; display: block; user-select: none; }
    </style>
</head>
<body>
    <canvas id="canvas" width="1280" height="800"></canvas>

    <script>
        if ('wakeLock' in navigator) {
            navigator.wakeLock.request('screen').catch(function(){});
        }

        const canvas = document.getElementById('canvas');
        const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
        let ws = null;
        let busy = false;

        function connect() {
            const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
            ws = new WebSocket(proto + location.host + '/ws');
            ws.binaryType = 'arraybuffer';

            ws.onmessage = function(event) {
                // Drop in-flight frame if tablet GPU is still rendering previous (Zero Lag/Bufferbloat)
                if (busy) return;
                busy = true;

                createImageBitmap(new Blob([event.data])).then(function(bmp) {
                    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
                    bmp.close(); // Immediately release hardware GPU texture memory
                    busy = false;
                }).catch(function() {
                    busy = false;
                });
            };

            ws.onclose = function() {
                setTimeout(connect, 1000);
            };

            ws.onerror = function() {
                try { ws.close(); } catch(e) {}
            };
        }

        connect();

        function sendMouse(action, e) {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            const rect = canvas.getBoundingClientRect();
            const touch = e.touches ? e.touches[0] : (e.changedTouches ? e.changedTouches[0] : e);
            if (!touch && action !== 'up') return;
            const x = touch ? Math.max(0, Math.min(1, (touch.clientX - rect.left) / rect.width)) : 0;
            const y = touch ? Math.max(0, Math.min(1, (touch.clientY - rect.top) / rect.height)) : 0;
            ws.send('m:' + action + ':' + x.toFixed(4) + ':' + y.toFixed(4));
        }

        canvas.addEventListener('touchstart', function(e) { e.preventDefault(); sendMouse('down', e); }, {passive: false});
        canvas.addEventListener('touchmove', function(e) { e.preventDefault(); sendMouse('move', e); }, {passive: false});
        canvas.addEventListener('touchend', function(e) { e.preventDefault(); sendMouse('up', e); }, {passive: false});
        canvas.addEventListener('mousedown', function(e) { sendMouse('down', e); });
        canvas.addEventListener('mousemove', function(e) { if (e.buttons) sendMouse('move', e); });
        canvas.addEventListener('mouseup', function(e) { sendMouse('up', e); });
    </script>
</body>
</html>
"""

class SystemTray:
    """Native Windows System Tray Icon (Like SuperDisplay desktop tray app)."""
    def __init__(self, server_instance):
        self.server = server_instance
        self.hwnd = None
        self.is_connected = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update_status(self, connected: bool):
        self.is_connected = connected
        if self.hwnd:
            tip = f"OpenDisplay - {'Connected (165Hz)' if connected else 'Waiting for USB...'}"
            nid = (self.hwnd, 0, win32gui.NIF_TIP, 0, 0, tip)
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, nid)

    def _run(self):
        msg_tray = win32con.WM_USER + 20
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = "OpenDisplayTray"
        wc.hInstance = win32gui.GetModuleHandle(None)

        try:
            class_atom = win32gui.RegisterClass(wc)
        except Exception:
            class_atom = "OpenDisplayTray"

        self.hwnd = win32gui.CreateWindow(
            class_atom, "OpenDisplayTray", 0, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )

        icon = None
        icon_candidates = [
            os.path.join(os.path.dirname(sys.executable), "app_icon.ico"),
            os.path.join(os.path.dirname(sys.executable), "_internal", "app_icon.ico"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "app_icon.ico")),
            os.path.join(os.getcwd(), "app_icon.ico"),
        ]
        for c in icon_candidates:
            if c and os.path.exists(c):
                try:
                    icon = win32gui.LoadImage(0, c, win32con.IMAGE_ICON, 0, 0, win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
                    if icon:
                        break
                except Exception:
                    pass
        if not icon:
            icon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)

        nid = (self.hwnd, 0, win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
               msg_tray, icon, "OpenDisplay - 165Hz Extended Monitor")
        win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

        win32gui.PumpMessages()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == win32con.WM_USER + 20:
            if lparam == win32con.WM_RBUTTONUP or lparam == win32con.WM_CONTEXTMENU:
                menu = win32gui.CreatePopupMenu()
                status_txt = "Status: USB Connected (165Hz)" if self.is_connected else "Status: Waiting for USB..."
                win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 1001, "OpenDisplay (165Hz Monitor)")
                win32gui.AppendMenu(menu, win32con.MF_STRING | win32con.MF_GRAYED, 1002, status_txt)
                win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
                win32gui.AppendMenu(menu, win32con.MF_STRING, 1003, "Open Tablet Viewer (Browser)")
                win32gui.AppendMenu(menu, win32con.MF_STRING, 1004, "Exit OpenDisplay")

                pos = win32gui.GetCursorPos()
                win32gui.SetForegroundWindow(hwnd)
                cmd = win32gui.TrackPopupMenu(menu, win32con.TPM_RETURNCMD, pos[0], pos[1], 0, hwnd, None)
                win32gui.DestroyMenu(menu)

                if cmd == 1003:
                    webbrowser.open(f"http://127.0.0.1:{PORT}/")
                elif cmd == 1004:
                    self.server.stop()
            elif lparam == win32con.WM_LBUTTONDBLCLK:
                webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def destroy(self):
        if self.hwnd:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self.hwnd, 0))

class USBMonitorThread(threading.Thread):
    """Monitors USB cable connection/disconnection (SuperDisplay behavior)."""
    def __init__(self, server_instance):
        super().__init__(daemon=True)
        self.server = server_instance
        self.last_connected = None

    def run(self):
        while self.server.is_running:
            try:
                adb = self.server.adb
                connected = False
                if adb and os.path.exists(adb):
                    res = subprocess.run(
                        [adb, "get-state"],
                        capture_output=True,
                        text=True,
                        creationflags=0x08000000,
                        timeout=2
                    )
                    connected = (res.returncode == 0 and "device" in res.stdout)

                if connected != self.last_connected:
                    self.last_connected = connected
                    if connected:
                        print("[OpenDisplay] Tablet USB plugged in! Activating 165Hz monitor...")
                        enable_virtual_display()
                        self.server.setup_usb_tunnel()
                        self.server.launch_tablet_viewer()
                        if hasattr(self.server, 'tray') and self.server.tray:
                            self.server.tray.update_status(True)
                    else:
                        if self.last_connected is not None:
                            print("[OpenDisplay] Tablet USB unplugged. Disconnecting virtual monitor...")
                            disable_virtual_display()
                            if hasattr(self.server, 'tray') and self.server.tray:
                                self.server.tray.update_status(False)
            except Exception:
                pass
            time.sleep(2.0)

class OpenDisplayServer:
    def __init__(self, port=PORT, display_idx=0, fps=60):
        self.port = port
        self.display_idx = display_idx
        self.fps = fps
        self.capture = DxgiScreenCapture(backend="auto")
        self.encoder = HardwareEncoder(codec="jpeg", fps=fps, quality=65)
        self.latest_frame_jpeg = None
        self.frame_condition = threading.Condition()
        self.frame_id = 0
        self.is_running = True
        self.adb = self._find_adb()
        self.tray = None
        self.httpd = None

    def _find_adb(self):
        candidates = [
            os.path.join(os.path.dirname(sys.executable), "_internal", "adb.exe"),
            os.path.join(os.path.dirname(sys.executable), "adb.exe"),
            os.path.join(os.getcwd(), "app_win", "adb.exe"),
            os.path.join(getattr(sys, "_MEIPASS", ""), "adb.exe"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "app_win", "adb.exe")),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "app_win", "adb.exe")),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return shutil.which("adb.exe") or shutil.which("adb")

    def setup_usb_tunnel(self):
        if not self.adb or not os.path.exists(self.adb):
            return
        try:
            subprocess.run([self.adb, "reverse", f"tcp:{STREAM_PORT}", f"tcp:{STREAM_PORT}"], capture_output=True, timeout=3, creationflags=0x08000000)
            subprocess.run([self.adb, "reverse", f"tcp:{PORT}", f"tcp:{PORT}"], capture_output=True, timeout=3, creationflags=0x08000000)
            print("[OpenDisplay] USB Reverse Tunnel established.")
        except Exception as e:
            print(f"[OpenDisplay] ADB reverse setup notice: {e}")

    def launch_tablet_viewer(self):
        if not self.adb or not os.path.exists(self.adb):
            return
        try:
            subprocess.run([self.adb, "shell", "am", "start", "-n", "com.display.usbclient/.MainActivity"], capture_output=True, timeout=3, creationflags=0x08000000)
        except Exception:
            pass

    def stop(self):
        self.is_running = False
        with self.frame_condition:
            self.frame_condition.notify_all()
        if self.tray:
            self.tray.destroy()
        disable_virtual_display()
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
        sys.exit(0)

    def capture_loop(self):
        interval = 1.0 / self.fps
        last_sub = None
        last_encode_time = 0

        while self.is_running:
            t0 = time.perf_counter()
            frame = self.capture.capture_frame(display_idx=self.display_idx)
            if frame is not None:
                now = time.perf_counter()
                # Fast 16x downsampled grid check (0.03ms): don't re-encode identical static screens
                sub = frame[::16, ::16].copy()
                if last_sub is not None and (now - last_encode_time < 0.25) and np.array_equal(sub, last_sub):
                    dt = time.perf_counter() - t0
                    sleep_time = interval - dt
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    continue

                last_sub = sub
                last_encode_time = now
                jpeg_bytes = self.encoder.encode_image(frame, format="jpeg", quality=65)

                with self.frame_condition:
                    self.latest_frame_jpeg = jpeg_bytes
                    self.frame_id += 1
                    self.frame_condition.notify_all()

            dt = time.perf_counter() - t0
            sleep_time = interval - dt
            if sleep_time > 0:
                time.sleep(sleep_time)

    def start(self):
        # Start tray icon
        self.tray = SystemTray(self)

        # Start USB plug/unplug watcher
        usb_watcher = USBMonitorThread(self)
        usb_watcher.start()

        # Start screen capture thread
        cap_thread = threading.Thread(target=self.capture_loop, daemon=True)
        cap_thread.start()

        server_instance = self

        class StreamHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def handle_websocket(self):
                key = self.headers.get("Sec-WebSocket-Key")
                if not key:
                    self.send_response(400)
                    self.end_headers()
                    return

                magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                accept = base64.b64encode(hashlib.sha1((key + magic).encode()).digest()).decode()
                self.send_response(101)
                self.send_header("Upgrade", "websocket")
                self.send_header("Connection", "Upgrade")
                self.send_header("Sec-WebSocket-Accept", accept)
                self.end_headers()

                sock = self.connection
                try:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                    sock.settimeout(3.0)
                except Exception:
                    pass

                last_sent_id = 0
                disp_info = server_instance.capture.list_displays()
                idx = server_instance.display_idx
                d = disp_info[idx] if idx < len(disp_info) else disp_info[0]
                left = d.get('left', 0)
                top = d.get('top', 0)
                w = d.get('width', 1280)
                h = d.get('height', 800)

                def send_ws_binary(payload):
                    length = len(payload)
                    if length < 126:
                        header = bytes([0x82, length])
                    elif length < 65536:
                        header = struct.pack("!BBH", 0x82, 126, length)
                    else:
                        header = struct.pack("!BBQ", 0x82, 127, length)
                    sock.sendall(header + payload)

                try:
                    while server_instance.is_running:
                        # 1. Read client mouse messages
                        try:
                            rlist, _, _ = select.select([sock], [], [], 0)
                            if rlist:
                                raw = sock.recv(2048)
                                if not raw:
                                    break
                                if len(raw) >= 6:
                                    payload_len = raw[1] & 0x7F
                                    offset = 2
                                    if payload_len == 126 and len(raw) >= 8:
                                        payload_len = struct.unpack("!H", raw[2:4])[0]
                                        offset = 4
                                    mask = raw[offset:offset + 4]
                                    data = raw[offset + 4:offset + 4 + payload_len]
                                    msg = bytes(b ^ mask[i % 4] for i, b in enumerate(data)).decode('utf-8', errors='ignore')
                                    if msg.startswith('m:'):
                                        parts = msg.split(':')
                                        if len(parts) == 4:
                                            action, nx, ny = parts[1], float(parts[2]), float(parts[3])
                                            tx = int(left + nx * w)
                                            ty = int(top + ny * h)
                                            ctypes.windll.user32.SetCursorPos(tx, ty)
                                            if action == 'down':
                                                ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                                            elif action == 'up':
                                                ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                        except Exception:
                            pass

                        # 2. Wait for next frame without busy-waiting
                        frame_data = None
                        with server_instance.frame_condition:
                            if server_instance.frame_id == last_sent_id:
                                server_instance.frame_condition.wait(timeout=0.03)
                            if server_instance.frame_id != last_sent_id:
                                frame_data = server_instance.latest_frame_jpeg
                                last_sent_id = server_instance.frame_id

                        if frame_data:
                            send_ws_binary(frame_data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            def do_GET(self):
                if self.path == "/" or self.path == "/index.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Cache-Control", "no-cache, no-store")
                    self.end_headers()
                    self.wfile.write(HTML_VIEWER.encode("utf-8"))

                elif self.path == "/ws":
                    self.handle_websocket()

                elif self.path == "/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=--frame")
                    self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                    self.send_header("Pragma", "no-cache")
                    self.end_headers()

                    try:
                        try:
                            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                        except Exception:
                            pass

                        last_id = 0
                        while server_instance.is_running:
                            frame_data = None
                            with server_instance.frame_condition:
                                if server_instance.frame_id == last_id:
                                    server_instance.frame_condition.wait(timeout=0.04)
                                if server_instance.frame_id != last_id:
                                    frame_data = server_instance.latest_frame_jpeg
                                    last_id = server_instance.frame_id

                            if frame_data is not None:
                                self.wfile.write(b"--frame\r\n")
                                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                                self.wfile.write(f"Content-Length: {len(frame_data)}\r\n\r\n".encode("ascii"))
                                self.wfile.write(frame_data)
                                self.wfile.write(b"\r\n")
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path.startswith("/mouse"):
                    try:
                        import urllib.parse
                        parsed = urllib.parse.urlparse(self.path)
                        params = urllib.parse.parse_qs(parsed.query)
                        action = params.get("action", ["move"])[0]
                        norm_x = float(params.get("x", [0])[0])
                        norm_y = float(params.get("y", [0])[0])

                        disp = server_instance.capture.list_displays()
                        idx = server_instance.display_idx
                        d = disp[idx] if idx < len(disp) else disp[0]
                        left = d.get('left', 0)
                        top = d.get('top', 0)
                        w = d.get('width', 1280)
                        h = d.get('height', 800)

                        target_x = int(left + norm_x * w)
                        target_y = int(top + norm_y * h)

                        ctypes.windll.user32.SetCursorPos(target_x, target_y)

                        if action == "down":
                            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                        elif action == "up":
                            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

                        self.send_response(204)
                        self.end_headers()
                    except Exception:
                        self.send_response(400)
                        self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

        self.httpd = ThreadingHTTPServer(("0.0.0.0", self.port), StreamHandler)
        print(f"[OpenDisplay] Running in background and System Tray (http://127.0.0.1:{self.port})")

        # Start native binary streamer on tcp:7070
        self.streamer_7070 = Streamer(
            host="0.0.0.0",
            port=STREAM_PORT,
            display_idx=self.display_idx,
            fps=self.fps,
            capture=self.capture,
            encoder=self.encoder,
            auto_forward=False,
        )
        self.streamer_7070.start_background()

        try:
            self.httpd.serve_forever()
        except KeyboardInterrupt:
            print("[OpenDisplay] Shutting down...")
        finally:
            self.stop()

if __name__ == "__main__":
    ensure_elevated()
    enable_virtual_display()

    temp_cap = DxgiScreenCapture(backend="auto")
    displays = temp_cap.list_displays()

    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        idx = int(sys.argv[1])
    else:
        idx = 1 if len(displays) > 1 else 0

    print(f"[OpenDisplay] Found {len(displays)} monitor(s). Streaming Display {idx}...")
    server = OpenDisplayServer(port=PORT, display_idx=idx, fps=60)
    server.start()
