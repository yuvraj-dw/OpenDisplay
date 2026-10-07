import socket
import threading
import unittest
from unittest.mock import MagicMock

import numpy as np

from server.streamer import Streamer
from server.transport.protocol import MSG_VIDEO


class TestStreamer(unittest.TestCase):
    def test_adb_setup(self):
        mock_adb = MagicMock()
        mock_adb.forward_port.return_value = True

        streamer = Streamer(adb_bridge=mock_adb, auto_forward=False)
        success = streamer.setup_adb()
        self.assertTrue(success)
        mock_adb.forward_port.assert_called_once_with(7070, 7070)

    def test_stream_frame_to_client(self):
        # Setup mock capture and encoder for fast reliable test
        mock_capture = MagicMock()
        synthetic_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        mock_capture.capture_frame.return_value = synthetic_frame

        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = b'test_encoded_nal_bytes'

        streamer = Streamer(
            host='127.0.0.1',
            port=0,  # OS will allocate free port
            capture=mock_capture,
            encoder=mock_encoder,
            auto_forward=False,
            fps=60,
        )

        server_sock = streamer.start_server()
        port = server_sock.getsockname()[1]

        received_packets = []
        client_ready = threading.Event()

        def client_worker():
            client_ready.set()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(('127.0.0.1', port))
                # Read header + payload
                header = s.recv(5)
                import struct
                total_len, msg_type = struct.unpack('>IB', header)
                payload_len = total_len - 1
                payload = b''
                while len(payload) < payload_len:
                    chunk = s.recv(payload_len - len(payload))
                    if not chunk:
                        break
                    payload += chunk
                received_packets.append((msg_type, payload))

        client_thread = threading.Thread(target=client_worker, daemon=True)
        client_thread.start()
        client_ready.wait()

        # Handle one client connection and send 1 frame
        client_sock, _ = server_sock.accept()
        try:
            # Verify TCP_NODELAY option is set
            nodelay_val = client_sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            self.assertNotEqual(nodelay_val, 0)

            streamer.send_single_frame(client_sock)
        finally:
            client_sock.close()
            streamer.stop()
            client_thread.join(timeout=1.0)

        self.assertEqual(len(received_packets), 1)
        msg_type, payload = received_packets[0]
        self.assertEqual(msg_type, MSG_VIDEO)
        self.assertEqual(payload, b'test_encoded_nal_bytes')

    def test_send_frame_capture_none(self):
        mock_capture = MagicMock()
        mock_capture.capture_frame.return_value = None
        mock_encoder = MagicMock()

        streamer = Streamer(capture=mock_capture, encoder=mock_encoder, auto_forward=False)
        mock_sock = MagicMock()
        success = streamer.send_single_frame(mock_sock)
        self.assertFalse(success)
        mock_sock.sendall.assert_not_called()

    def test_send_frame_encoder_empty(self):
        mock_capture = MagicMock()
        mock_capture.capture_frame.return_value = np.zeros((100, 100, 3), dtype=np.uint8)
        mock_encoder = MagicMock()
        mock_encoder.encode.return_value = b''

        streamer = Streamer(capture=mock_capture, encoder=mock_encoder, auto_forward=False)
        mock_sock = MagicMock()
        success = streamer.send_single_frame(mock_sock)
        self.assertFalse(success)
        mock_sock.sendall.assert_not_called()

    def test_context_manager(self):
        with Streamer(auto_forward=False) as streamer:
            self.assertIsNotNone(streamer)


if __name__ == '__main__':
    unittest.main()
