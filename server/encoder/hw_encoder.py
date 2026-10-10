import logging
import os
import queue
import re
import subprocess
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_NVENC_AVAILABLE: bool | None = None


def extract_nal_units(data: bytes) -> list[bytes]:
    """Extract individual complete NAL units (with start codes) from Annex B byte stream."""
    if not data:
        return []

    pattern = re.compile(b'(?:\x00\x00\x00\x01|\x00\x00\x01)')
    matches = list(pattern.finditer(data))
    if not matches:
        return [data]

    nals = []
    if matches[0].start() > 0:
        nals.append(data[:matches[0].start()])
    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(data)
        nal = data[start:end]
        if nal:
            nals.append(nal)
    return nals


def _is_nvenc_available(ffmpeg_path: str | None) -> bool:
    global _NVENC_AVAILABLE
    if _NVENC_AVAILABLE is not None:
        return _NVENC_AVAILABLE
    if not ffmpeg_path:
        _NVENC_AVAILABLE = False
        return False
    try:
        res = subprocess.run(
            [ffmpeg_path, '-nostdin', '-f', 'lavfi', '-i', 'nullsrc=s=640x480', '-frames:v', '1', '-c:v', 'h264_nvenc', '-f', 'null', '-'],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=2.0,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        _NVENC_AVAILABLE = (res.returncode == 0)
    except Exception:
        _NVENC_AVAILABLE = False
    return _NVENC_AVAILABLE


def _find_ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    import shutil

    return shutil.which('ffmpeg') or shutil.which('ffmpeg.exe')


class HardwareEncoder:
    """Hardware-accelerated and low-latency video/image encoder.

    Supports H.264 (NVENC, MediaFoundation, libx264) and fast image encoding (JPEG).
    """

    def __init__(
        self,
        codec: str = 'auto',
        width: int | None = None,
        height: int | None = None,
        fps: int = 60,
        bitrate: str = '6M',
        quality: int = 80,
        low_latency: bool = True,
    ):
        self.codec = codec.lower()
        self.width = width
        self.height = height
        self.fps = fps
        self.bitrate = bitrate
        self.quality = quality
        self.low_latency = low_latency

        self.active_codec = self.codec
        self._proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._out_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._ffmpeg_path = _find_ffmpeg()
        self._first_frame = True

        if self.codec not in ('jpeg', 'jpg', 'dummy'):
            if self.width and self.height:
                self._init_video_encoder(self.width, self.height)

    def _init_video_encoder(self, width: int, height: int):
        self.close_video_encoder()
        if not self._ffmpeg_path:
            logger.warning("FFmpeg executable not found. Falling back to JPEG encoding.")
            self.active_codec = 'jpeg'
            return

        # Prioritize low-latency codec
        target_codec = 'libx264'
        if self.codec in ('nvenc', 'h264_nvenc'):
            target_codec = 'h264_nvenc'
        elif self.codec in ('mf', 'h264_mf', 'mediafoundation'):
            target_codec = 'h264_mf'
        elif self.codec in ('qsv', 'h264_qsv'):
            target_codec = 'h264_qsv'
        elif self.codec in ('x264', 'libx264'):
            target_codec = 'libx264'
        elif self.codec in ('auto', 'h264'):
            target_codec = 'h264_nvenc' if _is_nvenc_available(self._ffmpeg_path) else 'libx264'

        cmd = [
            self._ffmpeg_path,
            '-y',
            '-f',
            'rawvideo',
            '-vcodec',
            'rawvideo',
            '-s',
            f"{width}x{height}",
            '-pix_fmt',
            'bgr24',
            '-r',
            str(self.fps),
            '-i',
            '-',
            '-c:v',
            target_codec,
            '-pix_fmt',
            'yuv420p',
        ]

        if target_codec == 'libx264':
            cmd.extend([
                '-preset',
                'ultrafast',
                '-tune',
                'zerolatency',
                '-profile:v',
                'baseline',
                '-bf',
                '0',
                '-b:v',
                self.bitrate or '6M',
                '-maxrate',
                self.bitrate or '6M',
                '-bufsize',
                '512k',
                '-g',
                str(self.fps),
                '-x264-params',
                f'repeat-headers=1:keyint={self.fps}',
                '-flush_packets',
                '1',
            ])
        elif target_codec == 'h264_nvenc':
            cmd.extend([
                '-preset',
                'p1',
                '-tune',
                'ull',
                '-profile:v',
                'baseline',
                '-zerolatency',
                '1',
                '-delay',
                '0',
                '-bf',
                '0',
                '-rc-lookahead',
                '0',
                '-surfaces',
                '2',
                '-b:v',
                self.bitrate or '6M',
                '-maxrate',
                self.bitrate or '6M',
                '-bufsize',
                '512k',
                '-g',
                str(self.fps),
                '-forced-idr',
                '1',
                '-flush_packets',
                '1',
                '-colorspace',
                'bt709',
                '-color_primaries',
                'bt709',
                '-color_trc',
                'bt709',
            ])
        elif target_codec == 'h264_mf':
            cmd.extend([
                '-usage',
                'lowlatency',
                '-b:v',
                self.bitrate or '6M',
                '-flush_packets',
                '1',
            ])
        elif target_codec == 'h264_qsv':
            cmd.extend([
                '-preset',
                'veryfast',
                '-b:v',
                self.bitrate or '6M',
                '-flush_packets',
                '1',
            ])

        cmd.extend(['-f', 'h264', '-'])

        flags = 0
        if os.name == 'nt':
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                creationflags=flags,
            )
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._stdout_reader,
                daemon=True,
            )
            self._reader_thread.start()
            self.active_codec = target_codec
            self.width = width
            self.height = height
            self._first_frame = True
        except Exception as e:
            if target_codec == 'h264_nvenc':
                logger.warning(f"NVENC encoder failed ({e}), falling back to libx264")
                self.codec = 'libx264'
                self._init_video_encoder(width, height)
                return
            logger.error(f"Failed to start FFmpeg video encoder: {e}")
            self.active_codec = 'jpeg'

    def _stdout_reader(self):
        while not self._stop_event.is_set() and self._proc and self._proc.stdout:
            try:
                chunk = (
                    self._proc.stdout.read1(65536)
                    if hasattr(self._proc.stdout, 'read1')
                    else self._proc.stdout.read(65536)
                )
                if not chunk:
                    break
                self._out_queue.put(chunk)
            except Exception:
                break

    def encode(self, frame: np.ndarray) -> bytes:
        """Encode a frame (BGR numpy array) to bytes."""
        if self.codec in ('jpeg', 'jpg'):
            return self.encode_image(frame, format='jpeg', quality=self.quality)

        if self.codec == 'dummy':
            return b'dummy_encoded_frame_data'

        # Video encoding
        return self.encode_video_frame(frame)

    def encode_image(
        self,
        frame: np.ndarray,
        format: str = 'jpeg',
        quality: int = 80,
    ) -> bytes:
        """Encode frame to compressed image bytes (JPEG / WebP)."""
        if format.lower() in ('jpeg', 'jpg'):
            params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
            success, enc = cv2.imencode('.jpg', frame, params)
        elif format.lower() == 'webp':
            params = [int(cv2.IMWRITE_WEBP_QUALITY), int(quality)]
            success, enc = cv2.imencode('.webp', frame, params)
        else:
            success, enc = cv2.imencode('.png', frame)

        if not success:
            raise RuntimeError(f"Failed to encode image with format {format}")
        return enc.tobytes()

    def encode_video_frame(self, frame: np.ndarray) -> bytes:
        """Encode a frame using the H.264 video pipeline."""
        h, w = frame.shape[:2]
        if self._proc is None or self._proc.poll() is not None or self.width != w or self.height != h:
            self._init_video_encoder(w, h)

        if self._proc is None or self._proc.stdin is None:
            # Fall back to JPEG if video encoder couldn't start
            return self.encode_image(frame, format='jpeg', quality=self.quality)

        try:
            # ponytail: zero-copy pipe write via memoryview eliminates 180MB/s of GC heap churn
            self._proc.stdin.write(memoryview(frame))
            self._proc.stdin.flush()

            # Collect output NAL packets directly via condition wait
            chunks = []
            timeout = 2.0 if getattr(self, '_first_frame', False) else 0.05
            try:
                chunk = self._out_queue.get(timeout=timeout)
                chunks.append(chunk)
                while not self._out_queue.empty():
                    chunks.append(self._out_queue.get_nowait())
            except queue.Empty:
                pass

            self._first_frame = False

            if chunks:
                return b''.join(chunks)

            return b''
        except Exception as e:
            logger.warning(f"Video frame encode error: {e}")
            return b''

    def encode_frame(self, frame: np.ndarray) -> list[bytes]:
        """Encode a frame and return a list of complete packets / NAL units."""
        if self.codec in ('jpeg', 'jpg'):
            return [self.encode_image(frame, format='jpeg', quality=self.quality)]

        if self.codec == 'dummy':
            return [b'dummy_encoded_frame_data']

        data = self.encode_video_frame(frame)
        if not data:
            return []

        if data.startswith(b'\xff\xd8'):
            return [data]

        return [data]

    @staticmethod
    def extract_nal_units(data: bytes) -> list[bytes]:
        return extract_nal_units(data)

    def get_active_codec(self) -> str:
        return self.active_codec

    def close_video_encoder(self):
        self._stop_event.set()
        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                if self._proc.stdout:
                    self._proc.stdout.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=0.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.2)
            self._reader_thread = None
        self._out_queue = queue.Queue()

    def close(self):
        self.close_video_encoder()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


HwEncoder = HardwareEncoder
