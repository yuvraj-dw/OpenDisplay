import logging
import threading
from typing import Any
import ctypes
from ctypes import wintypes
import numpy as np

# Enable Per-Monitor DPI Awareness so GetCursorPos and screen capture coordinates match 1:1
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Win32 structures for high-performance cursor rendering
class _POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]

class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('hCursor', wintypes.HICON),
        ('ptScreenPos', _POINT),
    ]

class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ('fIcon', wintypes.BOOL),
        ('xHotspot', wintypes.DWORD),
        ('yHotspot', wintypes.DWORD),
        ('hbmMask', wintypes.HBITMAP),
        ('hbmColor', wintypes.HBITMAP),
    ]

class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wintypes.DWORD),
        ('biWidth', wintypes.LONG),
        ('biHeight', wintypes.LONG),
        ('biPlanes', wintypes.WORD),
        ('biBitCount', wintypes.WORD),
        ('biCompression', wintypes.DWORD),
        ('biSizeImage', wintypes.DWORD),
        ('biXPelsPerMeter', wintypes.LONG),
        ('biYPelsPerMeter', wintypes.LONG),
        ('biClrUsed', wintypes.DWORD),
        ('biClrImportant', wintypes.DWORD),
    ]

try:
    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32
    _user32.GetCursorInfo.argtypes = [ctypes.c_void_p]
    _user32.GetCursorInfo.restype = wintypes.BOOL
    _user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.c_void_p]
    _user32.GetIconInfo.restype = wintypes.BOOL
    _user32.DrawIconEx.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
        ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH, wintypes.UINT
    ]
    _user32.DrawIconEx.restype = wintypes.BOOL
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.DeleteDC.restype = wintypes.BOOL
except Exception:
    pass

logger = logging.getLogger(__name__)


class DxgiScreenCapture:
    """Screen capture interface supporting DXGI (via dxcam), MSS, Windows GDI,
    and Headless synthetic mode.
    """

    def __init__(self, backend: str = 'auto'):
        self.requested_backend = backend.lower()
        self.backend = None
        self._thread_local = threading.local()
        self._dxcam_camera = None
        self._dxcam_idx = None
        self._dxcam_current_target = None
        self._cached_displays = None
        self._last_display_check_time = 0.0

        self._init_backend()

    @property
    def _sct(self):
        return getattr(self._thread_local, 'sct', None)

    @_sct.setter
    def _sct(self, value):
        self._thread_local.sct = value

    def _get_mss(self):
        sct = self._sct
        if sct is None:
            import mss
            sct = mss.mss()
            self._sct = sct
        return sct

    def _init_backend(self):
        if self.requested_backend in ('headless', 'dummy'):
            self.backend = 'headless'
            return

        if self.requested_backend in ('dxgi', 'dxcam'):
            if self._try_init_dxcam():
                self.backend = 'dxcam'
                return
            raise RuntimeError("DXGI/dxcam backend requested but unavailable.")

        if self.requested_backend == 'mss':
            if self._try_init_mss():
                self.backend = 'mss'
                return
            raise RuntimeError("MSS backend requested but unavailable.")

        if self.requested_backend == 'gdi':
            if self._try_init_gdi():
                self.backend = 'gdi'
                return
            raise RuntimeError("GDI backend requested but unavailable.")

        # 'auto' backend selection
        if self._try_init_dxcam():
            self.backend = 'dxcam'
        elif self._try_init_mss():
            self.backend = 'mss'
        elif self._try_init_gdi():
            self.backend = 'gdi'
        else:
            logger.warning("No native capture backend available, falling back to headless.")
            self.backend = 'headless'

    def _try_init_dxcam(self) -> bool:
        try:
            import dxcam  # type: ignore

            cam = dxcam.create()
            if cam is not None:
                del cam
                return True
        except Exception as e:
            logger.debug(f"dxcam unavailable: {e}")
        return False

    def _try_init_mss(self) -> bool:
        try:
            sct = self._get_mss()
            if sct.monitors and len(sct.monitors) > 0:
                return True
        except Exception as e:
            logger.debug(f"mss unavailable: {e}")
            sct = getattr(self._thread_local, 'sct', None)
            if sct:
                try:
                    sct.close()
                except Exception:
                    pass
                self._thread_local.sct = None
        return False

    def _try_init_gdi(self) -> bool:
        try:
            import win32api

            monitors = win32api.EnumDisplayMonitors()
            return len(monitors) > 0
        except Exception as e:
            logger.debug(f"gdi unavailable: {e}")
            return False

    def list_displays(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """List available display outputs with 2.0s caching to eliminate per-frame overhead."""
        import time
        now = time.time()
        if not force_refresh and self._cached_displays and (now - self._last_display_check_time < 2.0):
            return self._cached_displays

        displays = []
        if self.backend == 'dxcam':
            try:
                displays = self._list_displays_dxcam()
            except Exception as e:
                logger.warning(f"Error listing displays with dxcam: {e}")

        if not displays and (self.backend == 'mss' or self._sct is not None):
            try:
                displays = self._list_displays_mss()
            except Exception as e:
                logger.warning(f"Error listing displays with mss: {e}")

        if not displays and self.backend == 'gdi':
            try:
                displays = self._list_displays_gdi()
            except Exception as e:
                logger.warning(f"Error listing displays with gdi: {e}")

        if not displays:
            displays = self._list_displays_headless()

        self._cached_displays = displays
        self._last_display_check_time = now
        return displays

    def _parse_dxcam_outputs(self) -> list[dict[str, Any]]:
        """Parse dxcam.output_info() to extract precise (device_idx, output_idx) pairs."""
        import re
        import dxcam  # type: ignore

        try:
            info = dxcam.output_info()
            pattern = re.compile(
                r'Device\[(\d+)\]\s+Output\[(\d+)\]:\s*Res:\((\d+),\s*(\d+)\)\s*Rot:(\d+)\s*Primary:(\w+)'
            )
            outputs = []
            for m in pattern.finditer(info):
                outputs.append({
                    'device_idx': int(m.group(1)),
                    'output_idx': int(m.group(2)),
                    'width': int(m.group(3)),
                    'height': int(m.group(4)),
                    'rotation': int(m.group(5)),
                    'is_primary': (m.group(6).lower() == 'true')
                })
            return outputs
        except Exception as e:
            logger.debug(f"Failed parsing dxcam output info: {e}")
            return []

    def _list_displays_dxcam(self) -> list[dict[str, Any]]:
        import dxcam  # type: ignore

        dxcam_outs = self._parse_dxcam_outputs()
        mss_displays = self._list_displays_mss()
        displays = []
        for idx, out in enumerate(dxcam_outs):
            if idx < len(mss_displays):
                d = dict(mss_displays[idx])
                d['id'] = idx
                d['device_idx'] = out['device_idx']
                d['output_idx'] = out['output_idx']
                displays.append(d)
            else:
                displays.append({
                    'id': idx,
                    'name': f"Display {idx}",
                    'width': out['width'],
                    'height': out['height'],
                    'left': -out['width'] if idx > 0 else 0,
                    'top': 0,
                    'device_idx': out['device_idx'],
                    'output_idx': out['output_idx'],
                })
        return displays if displays else self._list_displays_headless()

    def _list_displays_mss(self) -> list[dict[str, Any]]:
        sct = self._get_mss()
        monitors = sct.monitors
        # In mss, index 0 is the combination of all monitors
        displays = []
        if len(monitors) > 1:
            for idx, m in enumerate(monitors[1:]):
                displays.append({
                    'id': idx,
                    'name': f"Display {idx}",
                    'width': int(m['width']),
                    'height': int(m['height']),
                    'left': int(m['left']),
                    'top': int(m['top']),
                })
        elif len(monitors) == 1:
            m = monitors[0]
            displays.append({
                'id': 0,
                'name': "Display 0",
                'width': int(m['width']),
                'height': int(m['height']),
                'left': int(m['left']),
                'top': int(m['top']),
            })
        return displays

    def _list_displays_gdi(self) -> list[dict[str, Any]]:
        import win32api

        monitors = win32api.EnumDisplayMonitors()
        displays = []
        for idx, (hmon, _, rect) in enumerate(monitors):
            left, top, right, bottom = rect
            displays.append({
                'id': idx,
                'name': f"Display {idx}",
                'width': right - left,
                'height': bottom - top,
                'left': left,
                'top': top,
            })
        return displays

    def _list_displays_headless(self) -> list[dict[str, Any]]:
        return [{
            'id': 0,
            'name': 'Headless Display 0',
            'width': 1920,
            'height': 1080,
            'left': 0,
            'top': 0,
        }]

    def capture_frame(self, display_idx: int = 0) -> np.ndarray | None:
        """Capture a single frame from the specified display index.

        Returns a numpy array of shape (H, W, 3) in BGR format.
        """
        displays = self.list_displays()
        if display_idx < 0 or (displays and display_idx >= len(displays)):
            raise IndexError(f"Display index {display_idx} out of range (total {len(displays)})")

        frame = None
        if self.backend == 'dxcam':
            try:
                frame = self._capture_dxcam(display_idx)
            except Exception as e:
                logger.warning(f"dxcam capture failed: {e}")

        # Only fallback to MSS if backend is not dxcam or if dxcam had an unrecoverable failure
        if frame is None and self.backend != 'dxcam' and (self.backend == 'mss' or self._sct is not None):
            try:
                frame = self._capture_mss(display_idx)
            except Exception as e:
                logger.warning(f"mss capture failed: {e}")

        if frame is None and self.backend == 'gdi':
            try:
                frame = self._capture_gdi(display_idx)
            except Exception as e:
                logger.warning(f"gdi capture failed: {e}")

        if frame is None and self.backend not in ('dxcam', 'mss', 'gdi'):
            frame = self._capture_headless(display_idx)

        if frame is not None:
            frame = self._draw_cursor(frame, display_idx)

        return frame

    def _draw_cursor(self, frame: np.ndarray, display_idx: int) -> np.ndarray:
        try:
            pt = _POINT()
            if not _user32.GetCursorPos(ctypes.byref(pt)):
                return frame

            # Get display coordinates
            left, top = 0, 0
            if self.backend == 'mss' or self._sct is not None:
                monitors = self._get_mss().monitors
                if len(monitors) > 1:
                    m_idx = display_idx + 1 if display_idx + 1 < len(monitors) else 1
                    left = monitors[m_idx].get('left', 0)
                    top = monitors[m_idx].get('top', 0)
            else:
                displays = self.list_displays()
                disp = displays[display_idx] if display_idx < len(displays) else displays[0]
                left = disp.get('left', 0)
                top = disp.get('top', 0)

            cx = pt.x - left
            cy = pt.y - top
            h, w = frame.shape[:2]

            # Cursor bounds check on target monitor
            if not (0 <= cx < w and 0 <= cy < h):
                return frame

            # 1. Try real Windows cursor extraction via DrawIconEx
            drawn = False
            ci = _CURSORINFO()
            ci.cbSize = ctypes.sizeof(_CURSORINFO)
            if _user32.GetCursorInfo(ctypes.byref(ci)) and ci.hCursor:
                ii = _ICONINFO()
                hx, hy = 0, 0
                if _user32.GetIconInfo(ci.hCursor, ctypes.byref(ii)):
                    hx = int(ii.xHotspot)
                    hy = int(ii.yHotspot)
                    if ii.hbmMask:
                        _gdi32.DeleteObject(ii.hbmMask)
                    if ii.hbmColor:
                        _gdi32.DeleteObject(ii.hbmColor)

                cur_w, cur_h = 32, 32
                bmi = _BITMAPINFOHEADER()
                bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
                bmi.biWidth = cur_w
                bmi.biHeight = -cur_h
                bmi.biPlanes = 1
                bmi.biBitCount = 32
                bmi.biCompression = 0

                p_bits = ctypes.c_void_p()
                hdc_mem = _gdi32.CreateCompatibleDC(None)
                hbm = _gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(p_bits), None, 0)
                old_bm = _gdi32.SelectObject(hdc_mem, hbm)

                try:
                    if _user32.DrawIconEx(hdc_mem, 0, 0, ci.hCursor, cur_w, cur_h, 0, None, 3):
                        buf = (ctypes.c_ubyte * (cur_w * cur_h * 4)).from_address(p_bits.value)
                        cur_rgba = np.frombuffer(buf, dtype=np.uint8).reshape((cur_h, cur_w, 4))
                        x0 = cx - hx
                        y0 = cy - hy
                        x1 = max(0, x0)
                        y1 = max(0, y0)
                        x2 = min(w, x0 + cur_w)
                        y2 = min(h, y0 + cur_h)

                        if x2 > x1 and y2 > y1:
                            src_x1 = x1 - x0
                            src_y1 = y1 - y0
                            src_x2 = src_x1 + (x2 - x1)
                            src_y2 = src_y1 + (y2 - y1)

                            sub_cur = cur_rgba[src_y1:src_y2, src_x1:src_x2]
                            alpha = sub_cur[:, :, 3:4] / 255.0
                            cur_bgr = sub_cur[:, :, :3]

                            if alpha.max() > 0:
                                frame[y1:y2, x1:x2] = (cur_bgr * alpha + frame[y1:y2, x1:x2] * (1.0 - alpha)).astype(np.uint8)
                                drawn = True
                            elif (cur_bgr > 0).any():
                                mask = (cur_bgr > 0).any(axis=2, keepdims=True)
                                np.copyto(frame[y1:y2, x1:x2], cur_bgr, where=mask)
                                drawn = True
                finally:
                    _gdi32.SelectObject(hdc_mem, old_bm)
                    _gdi32.DeleteObject(hbm)
                    _gdi32.DeleteDC(hdc_mem)

            # 2. High-visibility vector cursor fallback if icon extraction was blank
            if not drawn:
                import cv2
                scale = max(1.0, min(w, h) / 900.0)
                pts = np.array([
                    [cx, cy],
                    [cx, min(int(cy + 24 * scale), h - 1)],
                    [min(int(cx + 6 * scale), w - 1), min(int(cy + 18 * scale), h - 1)],
                    [min(int(cx + 12 * scale), w - 1), min(int(cy + 29 * scale), h - 1)],
                    [min(int(cx + 16 * scale), w - 1), min(int(cy + 27 * scale), h - 1)],
                    [min(int(cx + 10 * scale), w - 1), min(int(cy + 16 * scale), h - 1)],
                    [min(int(cx + 18 * scale), w - 1), min(int(cy + 16 * scale), h - 1)],
                ], dtype=np.int32)
                cv2.fillPoly(frame, [pts], (255, 255, 255))
                cv2.polylines(frame, [pts], True, (0, 0, 0), max(1, int(2 * scale)), cv2.LINE_AA)
        except Exception:
            pass
        return frame

    def capture(self, display_idx: int = 0) -> np.ndarray | None:
        """Alias for capture_frame."""
        return self.capture_frame(display_idx)

    def _capture_dxcam(self, display_idx: int) -> np.ndarray | None:
        import dxcam  # type: ignore

        displays = self.list_displays()
        dev_idx = 0
        out_idx = display_idx
        if display_idx < len(displays) and 'device_idx' in displays[display_idx]:
            dev_idx = displays[display_idx]['device_idx']
            out_idx = displays[display_idx]['output_idx']

        target = (dev_idx, out_idx)
        if self._dxcam_camera is None or getattr(self, '_dxcam_current_target', None) != target:
            if self._dxcam_camera is not None:
                try:
                    self._dxcam_camera.stop()
                except Exception:
                    pass
                del self._dxcam_camera
                self._dxcam_camera = None

            self._dxcam_camera = dxcam.create(device_idx=dev_idx, output_idx=out_idx)
            if self._dxcam_camera:
                self._dxcam_camera.start(target_fps=60, video_mode=True)
            self._dxcam_current_target = target
            self._dxcam_idx = display_idx

        if self._dxcam_camera:
            frame = self._dxcam_camera.get_latest_frame()
            if frame is not None:
                if frame.shape[2] == 4:
                    return frame[:, :, :3]
                return frame
        return None

    def _capture_mss(self, display_idx: int) -> np.ndarray | None:
        sct = self._get_mss()
        monitors = sct.monitors
        if len(monitors) > 1:
            mon_idx = display_idx + 1
            if mon_idx >= len(monitors):
                mon_idx = 1
            monitor = monitors[mon_idx]
        elif len(monitors) == 1:
            monitor = monitors[0]
        else:
            return None

        try:
            shot = sct.grab(monitor)
        except AttributeError:
            import mss
            sct = mss.mss()
            self._thread_local.sct = sct
            shot = sct.grab(monitor)

        # shot is BGRA
        frame = np.asarray(shot, dtype=np.uint8)
        return frame[:, :, :3]

    def _capture_gdi(self, display_idx: int) -> np.ndarray | None:
        import win32api
        import win32con
        import win32gui
        import win32ui

        monitors = win32api.EnumDisplayMonitors()
        if display_idx >= len(monitors):
            display_idx = 0
        _, _, rect = monitors[display_idx]
        left, top, right, bottom = rect
        w = right - left
        h = bottom - top

        hwin = win32gui.GetDesktopWindow()
        hwindc = win32gui.GetWindowDC(hwin)
        srcdc = win32ui.CreateDCFromHandle(hwindc)
        memdc = srcdc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(srcdc, w, h)
        memdc.SelectObject(bmp)
        memdc.BitBlt((0, 0), (w, h), srcdc, (left, top), win32con.SRCCOPY)

        signed_ints_array = bmp.GetBitmapBits(True)
        img = np.frombuffer(signed_ints_array, dtype=np.uint8).reshape((h, w, 4))

        win32gui.DeleteObject(bmp.GetHandle())
        memdc.DeleteDC()
        srcdc.DeleteDC()
        win32gui.ReleaseDC(hwin, hwindc)

        return img[:, :, :3]

    def _capture_headless(self, display_idx: int) -> np.ndarray:
        # Return a synthetic test frame
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # Add a subtle gradient or test color so it's not all zeros
        frame[:, :, 0] = 64
        frame[:, :, 1] = 128
        frame[:, :, 2] = 200
        return frame

    def close(self):
        sct = getattr(self._thread_local, 'sct', None)
        if sct:
            try:
                sct.close()
            except Exception:
                pass
            self._thread_local.sct = None
        if self._dxcam_camera:
            try:
                self._dxcam_camera.stop()
            except Exception:
                pass
            del self._dxcam_camera
            self._dxcam_camera = None
            self._dxcam_current_target = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
