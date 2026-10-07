import logging
import queue
import subprocess
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)


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
        bitrate: str = '20M',
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
        elif self.codec in ('x264', 'libx264', 'h264', 'auto'):
            target_codec = 'libx264'

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
        ]

        if target_codec == 'libx264':
            cmd.extend([
                '-preset',
                'ultrafast',
                '-tune',
                'zerolatency',
                '-bf',
                '0',
                '-b:v',
                self.bitrate,
                '-maxrate',
                self.bitrate,
                '-bufsize',
                '2M',
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
                'll',
                '-zerolatency',
                '1',
                '-delay',
                '0',
                '-b:v',
                self.bitrate,
                '-flush_packets',
                '1',
            ])
        elif target_codec == 'h264_mf':
            cmd.extend([
                '-usage',
                'lowlatency',
                '-b:v',
                self.bitrate,
                '-flush_packets',
                '1',
            ])

        cmd.extend(['-f', 'h264', '-'])

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
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
        except Exception as e:
            logger.error(f"Failed to start FFmpeg video encoder: {e}")
            self.active_codec = 'jpeg'

    def _stdout_reader(self):
        while not self._stop_event.is_set() and self._proc and self._proc.stdout:
            try:
                # read1 is non-blocking on buffers
                chunk = (
                    self._proc.stdout.read1(65536)
                    if hasattr(self._proc.stdout, 'read1')
                    else self._proc.stdout.read(4096)
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
            # Write raw frame bytes
            self._proc.stdin.write(frame.tobytes())
            self._proc.stdin.flush()

            # Collect output NAL packets
            chunks = []
            start_time = time.time()
            timeout = 0.1  # 100ms max wait for zerolatency frame

            while time.time() - start_time < timeout:
                try:
                    chunk = self._out_queue.get(timeout=0.005)
                    chunks.append(chunk)
                    while not self._out_queue.empty():
                        chunks.append(self._out_queue.get_nowait())
                    break
                except queue.Empty:
                    pass

            if chunks:
                return b''.join(chunks)

            # If no packet came out (e.g. initial buffer), return empty or fallback
            return self.encode_image(frame, format='jpeg', quality=self.quality)
        except Exception as e:
            logger.warning(f"Video frame encode error: {e}, falling back to JPEG")
            return self.encode_image(frame, format='jpeg', quality=self.quality)

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
