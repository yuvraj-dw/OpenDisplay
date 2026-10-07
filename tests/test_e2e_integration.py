import json
import logging
import socket
import struct
import threading
import time
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from server.capture.dxgi_capture import DxgiScreenCapture
from server.encoder.hw_encoder import HardwareEncoder
from server.streamer import StreamServer, Streamer
from server.transport.adb_bridge import AdbBridge
from server.transport.protocol import HEADER_FORMAT, HEADER_SIZE, MSG_CONFIG, MSG_VIDEO

logger = logging.getLogger(__name__)


class SimulatedAndroidClient:
    """Simulates Android tablet StreamReceiver.kt connecting over USB tunnel.

    Connects to localhost, performs protocol framing unmarshaling (>IB),
    tracks received MSG_CONFIG and MSG_VIDEO frames, timestamps, and throughput metrics.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7070, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.is_running = True

        self.configs: list[dict] = []
        self.frames: list[bytes] = []
        self.frame_timestamps: list[float] = []
        self.total_bytes_received = 0

        self.connected_event = threading.Event()
        self.config_received_event = threading.Event()
        self.first_frame_event = threading.Event()

        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _read_exact(self, sock: socket.socket, num_bytes: int) -> bytes:
        buf = bytearray()
        while len(buf) < num_bytes and self.is_running:
            chunk = sock.recv(num_bytes - len(buf))
            if not chunk:
                raise ConnectionResetError("Remote server closed streaming socket")
            buf.extend(chunk)
        return bytes(buf)

    def _run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            with self._lock:
                self._sock = s
            self.connected_event.set()

            while self.is_running:
                # 1. Read protocol header: 4 bytes totalLen, 1 byte msgType
                header_data = self._read_exact(s, HEADER_SIZE)
                total_len, msg_type = struct.unpack(HEADER_FORMAT, header_data)
                if total_len < 1:
                    raise ValueError(f"Invalid packet length: {total_len}")

                payload_len = total_len - 1
                payload = self._read_exact(s, payload_len) if payload_len > 0 else b""
                recv_time = time.perf_counter()

                with self._lock:
                    self.total_bytes_received += HEADER_SIZE + payload_len
                    if msg_type == MSG_CONFIG:
                        cfg = json.loads(payload.decode("utf-8"))
                        self.configs.append(cfg)
                        self.config_received_event.set()
                    elif msg_type == MSG_VIDEO:
                        self.frames.append(payload)
                        self.frame_timestamps.append(recv_time)
                        if not self.first_frame_event.is_set():
                            self.first_frame_event.set()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            with self._lock:
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None

    def get_throughput_stats(self) -> dict[str, float]:
        with self._lock:
            frame_count = len(self.frames)
            if frame_count < 2:
                return {
                    'frame_count': frame_count,
                    'duration_s': 0.0,
                    'fps': 0.0,
                    'avg_interval_ms': 0.0,
                    'throughput_kbps': 0.0,
                    'total_bytes': self.total_bytes_received,
                }

            duration = self.frame_timestamps[-1] - self.frame_timestamps[0]
            intervals = [
                self.frame_timestamps[i] - self.frame_timestamps[i - 1]
                for i in range(1, frame_count)
            ]
            avg_interval_ms = (sum(intervals) / len(intervals)) * 1000.0
            fps = (frame_count - 1) / duration if duration > 0 else 0.0
            throughput_kbps = (self.total_bytes_received / 1024.0) / duration if duration > 0 else 0.0

            return {
                'frame_count': frame_count,
                'duration_s': duration,
                'fps': fps,
                'avg_interval_ms': avg_interval_ms,
                'throughput_kbps': throughput_kbps,
                'total_bytes': self.total_bytes_received,
            }

    def stop(self):
        self.is_running = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)


class TestE2EIntegration(unittest.TestCase):
    """End-to-end integration test simulating the entire USB streaming pipeline.

    Starts host StreamServer on 127.0.0.1:7070, connects simulated Android client,
    and verifies config handshake, video frame streaming, timing, throughput,
    and clean shutdown.
    """

    def setUp(self):
        self.servers_to_stop: list[StreamServer] = []
        self.clients_to_stop: list[SimulatedAndroidClient] = []

    def tearDown(self):
        for client in self.clients_to_stop:
            try:
                client.stop()
            except Exception:
                pass
        for server in self.servers_to_stop:
            try:
                server.stop()
            except Exception:
                pass

    def test_e2e_pipeline_on_port_7070(self):
        """Simulates full USB streaming pipeline on default port 7070.

        Verifies:
        1. ADB forward port 7070 setup.
        2. StreamServer startup and listening on 127.0.0.1:7070.
        3. Android client connection over the USB tunnel.
        4. MSG_CONFIG handshake received with correct dimensions and FPS.
        5. Continuous MSG_VIDEO frame transmission with valid image data.
        6. Inter-frame timing and throughput metrics.
        7. Clean shutdown of both host server and client.
        """
        # 1. Setup mock ADB bridge simulating successful `adb forward tcp:7070 tcp:7070`
        mock_adb = MagicMock(spec=AdbBridge)
        mock_adb.forward_port.return_value = True

        # Headless capture simulating secondary monitor (1920x1080)
        capture = DxgiScreenCapture(backend='headless')
        # Fast JPEG hardware encoder
        encoder = HardwareEncoder(codec='jpeg', quality=80)

        # 2. Start host StreamServer on 127.0.0.1:7070
        server = StreamServer(
            host='127.0.0.1',
            port=7070,
            display_idx=0,
            fps=60,
            adb_bridge=mock_adb,
            capture=capture,
            encoder=encoder,
            auto_forward=True,
        )
        self.servers_to_stop.append(server)
        server.start_background()

        # Verify ADB port forward was invoked for USB tunnel
        mock_adb.forward_port.assert_called_once_with(7070, 7070)

        # 3. Simulate Android client connecting over the USB tunnel (localhost:7070)
        client = SimulatedAndroidClient(host='127.0.0.1', port=7070)
        self.clients_to_stop.append(client)
        client.start()

        # Wait for client connection
        connected = client.connected_event.wait(timeout=2.0)
        self.assertTrue(connected, "Client failed to connect to StreamServer on 127.0.0.1:7070")

        # 4. Verify message handshake (MSG_CONFIG)
        config_received = client.config_received_event.wait(timeout=2.0)
        self.assertTrue(config_received, "Failed to receive MSG_CONFIG handshake from server")

        with client._lock:
            self.assertEqual(len(client.configs), 1)
            cfg = client.configs[0]
            self.assertIn("width", cfg)
            self.assertIn("height", cfg)
            self.assertIn("fps", cfg)
            self.assertEqual(cfg["width"], 1920)
            self.assertEqual(cfg["height"], 1080)
            self.assertEqual(cfg["fps"], 60)

        # 5. Verify video frame transmission (MSG_VIDEO)
        first_frame = client.first_frame_event.wait(timeout=2.0)
        self.assertTrue(first_frame, "Failed to receive initial MSG_VIDEO frame")

        # Let the pipeline stream for ~0.4 seconds to collect multiple frames
        time.sleep(0.4)

        with client._lock:
            frame_count = len(client.frames)
            self.assertGreaterEqual(frame_count, 5, f"Expected at least 5 frames, got {frame_count}")

            # Verify that the received frames are valid decodable image frames
            sample_frame_bytes = client.frames[0]
            self.assertGreater(len(sample_frame_bytes), 0)
            decoded = cv2.imdecode(np.frombuffer(sample_frame_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertIsNotNone(decoded, "Received video frame payload could not be decoded as image")
            self.assertEqual(decoded.shape[0], 1080)
            self.assertEqual(decoded.shape[1], 1920)

        # 6. Verify frame timing and throughput
        stats = client.get_throughput_stats()
        self.assertGreater(stats['fps'], 10.0, f"Streaming FPS too low: {stats['fps']}")
        self.assertGreater(stats['throughput_kbps'], 50.0, f"Throughput too low: {stats['throughput_kbps']} KB/s")
        self.assertGreater(stats['avg_interval_ms'], 0.0)

        logger.info(
            f"[E2E Pipeline Port 7070] Received {stats['frame_count']} frames in {stats['duration_s']:.2f}s "
            f"({stats['fps']:.1f} FPS, avg interval: {stats['avg_interval_ms']:.1f}ms, "
            f"throughput: {stats['throughput_kbps']:.1f} KB/s)"
        )

        # 7. Clean shutdown
        client.stop()
        server.stop()
        self.assertFalse(server.is_running)

    def test_e2e_reconnection_robustness(self):
        """Simulates USB cable disconnect and reconnect while server remains active."""
        capture = DxgiScreenCapture(backend='headless')
        encoder = HardwareEncoder(codec='jpeg', quality=75)

        # Use dynamic free port
        server = StreamServer(
            host='127.0.0.1',
            port=0,
            fps=60,
            capture=capture,
            encoder=encoder,
            auto_forward=False,
        )
        self.servers_to_stop.append(server)
        server.start_background()
        port = server.port

        # Session 1: Client 1 connects, receives config and frames, then disconnects (unplug)
        client1 = SimulatedAndroidClient(host='127.0.0.1', port=port)
        self.clients_to_stop.append(client1)
        client1.start()

        self.assertTrue(client1.config_received_event.wait(timeout=2.0))
        self.assertTrue(client1.first_frame_event.wait(timeout=2.0))
        time.sleep(0.15)

        with client1._lock:
            self.assertGreaterEqual(len(client1.frames), 2)

        client1.stop()
        time.sleep(0.1)

        # Session 2: Client 2 connects (replug) to the still-running server
        client2 = SimulatedAndroidClient(host='127.0.0.1', port=port)
        self.clients_to_stop.append(client2)
        client2.start()

        self.assertTrue(client2.config_received_event.wait(timeout=2.0))
        self.assertTrue(client2.first_frame_event.wait(timeout=2.0))
        time.sleep(0.15)

        with client2._lock:
            self.assertGreaterEqual(len(client2.frames), 2)
            self.assertEqual(len(client2.configs), 1)

        client2.stop()
        server.stop()

    def test_e2e_server_context_manager(self):
        """Verifies clean context management and resource release."""
        mock_adb = MagicMock()
        mock_adb.forward_port.return_value = True

        with StreamServer(
            host='127.0.0.1',
            port=0,
            adb_bridge=mock_adb,
            capture=DxgiScreenCapture(backend='headless'),
            encoder=HardwareEncoder(codec='jpeg'),
            auto_forward=False,
        ) as server:
            server.start_background()
            port = server.port

            client = SimulatedAndroidClient(host='127.0.0.1', port=port)
            self.clients_to_stop.append(client)
            client.start()

            self.assertTrue(client.config_received_event.wait(timeout=2.0))
            self.assertTrue(client.first_frame_event.wait(timeout=2.0))
            client.stop()

        self.assertFalse(server.is_running)

    def test_e2e_server_abrupt_shutdown(self):
        """Verifies that when server stops abruptly, client cleanly detects EOF/reset."""
        server = StreamServer(
            host='127.0.0.1',
            port=0,
            capture=DxgiScreenCapture(backend='headless'),
            encoder=HardwareEncoder(codec='dummy'),
            auto_forward=False,
        )
        self.servers_to_stop.append(server)
        server.start_background()
        port = server.port

        client = SimulatedAndroidClient(host='127.0.0.1', port=port)
        self.clients_to_stop.append(client)
        client.start()

        self.assertTrue(client.config_received_event.wait(timeout=2.0))
        self.assertTrue(client.first_frame_event.wait(timeout=2.0))

        # Abruptly stop server
        server.stop()
        time.sleep(0.1)

        # Client thread should terminate or detect socket close without hanging
        client.stop()
        self.assertFalse(server.is_running)

    def test_benchmark_latency_integration(self):
        """Verifies that benchmark_latency utility runs and measures timer precision."""
        from tools.benchmark_latency import (
            create_latency_stopwatch,
            measure_system_timer_resolution,
            run_headless_benchmark,
        )

        res = measure_system_timer_resolution(samples=100)
        self.assertIn('min_resolution_us', res)
        self.assertIn('avg_resolution_us', res)
        self.assertGreater(res['samples'], 0)
        self.assertLess(res['min_resolution_us'], 5000.0)  # Microsecond order

        headless_stats = run_headless_benchmark(duration=0.2, interval=0.016, log_output=False)
        self.assertGreaterEqual(headless_stats['ticks'], 5)
        self.assertGreater(headless_stats['avg_fps'], 10.0)

        # Test stopwatch GUI initialization in test mode
        gui_result = create_latency_stopwatch(test_mode_ticks=3)
        self.assertIsNotNone(gui_result)
        if isinstance(gui_result, dict) and 'tick_count' in gui_result:
            self.assertGreaterEqual(gui_result['tick_count'], 3)


if __name__ == '__main__':
    unittest.main()
