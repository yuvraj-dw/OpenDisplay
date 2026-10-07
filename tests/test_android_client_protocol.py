import json
import socket
import struct
import threading
import time
import unittest

from server.transport.protocol import (
    HEADER_FORMAT,
    HEADER_SIZE,
    MSG_CONFIG,
    MSG_HEARTBEAT,
    MSG_VIDEO,
    pack_message,
    unpack_header,
)


class AndroidStreamProtocolParser:
    """Simulates the exact stream-unmarshaling logic executed by Android's

    StreamReceiver.kt (DataInputStream readInt + readByte + readFully).
    """

    def __init__(self):
        self.buffer = bytearray()
        self.parsed_messages: list[tuple[int, bytes]] = []

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        """Appends incoming TCP byte stream chunk and extracts all complete

        frames.
        """
        self.buffer.extend(chunk)
        new_messages = []

        while len(self.buffer) >= HEADER_SIZE:
            total_len, msg_type = struct.unpack_from(HEADER_FORMAT, self.buffer, 0)
            if total_len < 1:
                raise ValueError(f"Invalid packet total length: {total_len}")

            payload_len = total_len - 1
            frame_len = HEADER_SIZE + payload_len

            if len(self.buffer) < frame_len:
                # Need more bytes to complete payload
                break

            payload = bytes(self.buffer[HEADER_SIZE:frame_len])
            del self.buffer[:frame_len]
            message = (msg_type, payload)
            new_messages.append(message)
            self.parsed_messages.append(message)

        return new_messages


class AndroidStreamReceiverClient:
    """Python reference implementation of StreamReceiver.kt socket listener

    with auto-reconnect, exact header parsing, and event callbacks.
    """

    def __init__(self, host: str, port: int, reconnect_delay: float = 0.05):
        self.host = host
        self.port = port
        self.reconnect_delay = reconnect_delay
        self.is_running = True

        self.connected_count = 0
        self.disconnected_count = 0
        self.received_configs: list[dict] = []
        self.received_videos: list[bytes] = []
        self.received_heartbeats: list[bytes] = []

        self._thread: threading.Thread | None = None
        self._active_sock: socket.socket | None = None
        self._lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _read_exact(self, sock: socket.socket, num_bytes: int) -> bytes:
        data = bytearray()
        while len(data) < num_bytes and self.is_running:
            chunk = sock.recv(num_bytes - len(data))
            if not chunk:
                raise ConnectionResetError("Socket stream closed by remote host")
            data.extend(chunk)
        return bytes(data)

    def _run(self):
        while self.is_running:
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(1.0)
                sock.connect((self.host, self.port))
                sock.settimeout(2.0)

                with self._lock:
                    self._active_sock = sock
                    self.connected_count += 1

                while self.is_running:
                    # 1. Read header: 4 bytes totalLen, 1 byte msgType
                    header_bytes = self._read_exact(sock, HEADER_SIZE)
                    total_len, msg_type = struct.unpack(HEADER_FORMAT, header_bytes)
                    if total_len < 1:
                        raise ValueError(f"Invalid packet total length: {total_len}")

                    # 2. Read payload: totalLen - 1 bytes
                    payload_len = total_len - 1
                    payload = self._read_exact(sock, payload_len) if payload_len > 0 else b""

                    # 3. Route message
                    if msg_type == MSG_CONFIG:
                        config_data = json.loads(payload.decode("utf-8"))
                        with self._lock:
                            self.received_configs.append(config_data)
                    elif msg_type == MSG_VIDEO:
                        with self._lock:
                            self.received_videos.append(payload)
                    elif msg_type == MSG_HEARTBEAT:
                        with self._lock:
                            self.received_heartbeats.append(payload)

            except (ConnectionRefusedError, ConnectionResetError, socket.timeout, OSError, ValueError):
                if self.is_running:
                    with self._lock:
                        self.disconnected_count += 1
                    time.sleep(self.reconnect_delay)
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
                with self._lock:
                    if self._active_sock == sock:
                        self._active_sock = None

    def stop(self):
        self.is_running = False
        with self._lock:
            if self._active_sock:
                try:
                    self._active_sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._active_sock.close()
                except Exception:
                    pass
                self._active_sock = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


class TestAndroidClientProtocol(unittest.TestCase):
    """Verifies binary protocol fidelity, packet boundaries, chunking, and

    reconnection.
    """

    def test_protocol_constants_and_header_format(self):
        self.assertEqual(MSG_CONFIG, 1)
        self.assertEqual(MSG_VIDEO, 2)
        self.assertEqual(MSG_HEARTBEAT, 3)
        self.assertEqual(HEADER_SIZE, 5)

        # Test header structure (>IB: 4 bytes uint32 + 1 byte uint8)
        packed = struct.pack(HEADER_FORMAT, 10, MSG_VIDEO)
        self.assertEqual(len(packed), 5)
        total_len, msg_type = struct.unpack(HEADER_FORMAT, packed)
        self.assertEqual(total_len, 10)
        self.assertEqual(msg_type, MSG_VIDEO)

    def test_single_packet_parsing(self):
        parser = AndroidStreamProtocolParser()
        payload = b"\x00\x00\x00\x01\x67\x42\x00\x1f"  # H.264 SPS NAL unit
        packet = pack_message(MSG_VIDEO, payload)

        messages = parser.feed(packet)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0], (MSG_VIDEO, payload))
        self.assertEqual(len(parser.buffer), 0)

    def test_multiple_consecutive_packets_in_single_buffer(self):
        parser = AndroidStreamProtocolParser()
        config_payload = b'{"width": 2560, "height": 1600, "fps": 60}'
        video_payload_1 = b"\x00\x00\x00\x01\x65IDR_FRAME_1"
        video_payload_2 = b"\x00\x00\x00\x01\x41NON_IDR_FRAME_2"
        heartbeat_payload = b""

        stream_data = (
            pack_message(MSG_CONFIG, config_payload)
            + pack_message(MSG_VIDEO, video_payload_1)
            + pack_message(MSG_VIDEO, video_payload_2)
            + pack_message(MSG_HEARTBEAT, heartbeat_payload)
        )

        messages = parser.feed(stream_data)
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0], (MSG_CONFIG, config_payload))
        self.assertEqual(messages[1], (MSG_VIDEO, video_payload_1))
        self.assertEqual(messages[2], (MSG_VIDEO, video_payload_2))
        self.assertEqual(messages[3], (MSG_HEARTBEAT, heartbeat_payload))
        self.assertEqual(len(parser.buffer), 0)

    def test_chunked_transmission_byte_by_byte(self):
        parser = AndroidStreamProtocolParser()
        payload = b"CHUNKED_PAYLOAD_TEST_DATA"
        packet = pack_message(MSG_VIDEO, payload)

        # Feed 1 byte at a time
        for i in range(len(packet) - 1):
            msgs = parser.feed(packet[i : i + 1])
            self.assertEqual(len(msgs), 0, f"Premature message emitted at byte {i}")

        # The last byte should complete the frame
        last_msgs = parser.feed(packet[-1:])
        self.assertEqual(len(last_msgs), 1)
        self.assertEqual(last_msgs[0], (MSG_VIDEO, payload))
        self.assertEqual(len(parser.buffer), 0)

    def test_chunked_arbitrary_splits_across_headers(self):
        """Splits data mid-header and mid-payload across arbitrary packet

        boundaries.
        """
        parser = AndroidStreamProtocolParser()
        payload = b"A" * 100
        packet = pack_message(MSG_VIDEO, payload)

        # Split into arbitrary chunk sizes (e.g., 2 bytes, 10 bytes, 17 bytes)
        chunks = [packet[:2], packet[2:7], packet[7:25], packet[25:50], packet[50:]]
        all_messages = []
        for chunk in chunks:
            all_messages.extend(parser.feed(chunk))

        self.assertEqual(len(all_messages), 1)
        self.assertEqual(all_messages[0], (MSG_VIDEO, payload))

    def test_large_video_nal_chunked_transmission(self):
        """Verifies parsing of a large 256 KB video frame split into standard

        1460-byte MTUs.
        """
        parser = AndroidStreamProtocolParser()
        large_payload = b"\x00\x00\x00\x01\x65" + (b"\xAA\xBB\xCC\xDD" * 65536)
        packet = pack_message(MSG_VIDEO, large_payload)

        mtu = 1460
        all_messages = []
        for offset in range(0, len(packet), mtu):
            chunk = packet[offset : offset + mtu]
            all_messages.extend(parser.feed(chunk))

        self.assertEqual(len(all_messages), 1)
        self.assertEqual(all_messages[0], (MSG_VIDEO, large_payload))
        self.assertEqual(len(parser.buffer), 0)

    def test_invalid_packet_length_raises_error(self):
        parser = AndroidStreamProtocolParser()
        # total_len = 0 is invalid since total_len must be at least 1 (1 byte type + >=0 payload)
        invalid_packet = struct.pack(HEADER_FORMAT, 0, MSG_CONFIG)
        with self.assertRaises(ValueError):
            parser.feed(invalid_packet)

    def test_live_tcp_socket_streaming(self):
        """Integration test with a real TCP server and Android stream receiver

        client.
        """
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        client = AndroidStreamReceiverClient(host="127.0.0.1", port=port, reconnect_delay=0.05)
        client.start()

        conn, _ = server_sock.accept()
        try:
            config = {"width": 1920, "height": 1080, "fps": 60}
            conn.sendall(pack_message(MSG_CONFIG, json.dumps(config).encode("utf-8")))

            for i in range(5):
                frame_data = f"FRAME_NAL_{i}".encode("utf-8")
                conn.sendall(pack_message(MSG_VIDEO, frame_data))

            # Allow client to process
            time.sleep(0.1)

            with client._lock:
                self.assertEqual(len(client.received_configs), 1)
                self.assertEqual(client.received_configs[0], config)
                self.assertEqual(len(client.received_videos), 5)
                self.assertEqual(client.received_videos[0], b"FRAME_NAL_0")
                self.assertEqual(client.received_videos[4], b"FRAME_NAL_4")
        finally:
            conn.close()
            server_sock.close()
            client.stop()

    def test_live_tcp_reconnection_after_server_restart(self):
        """Tests that client automatically reconnects and resumes receiving

        when server drops and re-accepts connections.
        """
        # Phase 1: Initial server session
        server_sock_1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock_1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock_1.bind(("127.0.0.1", 0))
        port = server_sock_1.getsockname()[1]
        server_sock_1.listen(1)

        client = AndroidStreamReceiverClient(host="127.0.0.1", port=port, reconnect_delay=0.05)
        client.start()

        conn_1, _ = server_sock_1.accept()
        conn_1.sendall(pack_message(MSG_VIDEO, b"FRAME_BEFORE_DISCONNECT"))
        time.sleep(0.05)

        # Abruptly terminate Phase 1 connection and close server socket
        conn_1.close()
        server_sock_1.close()
        time.sleep(0.1)  # Client detects disconnect and enters retry loop

        # Phase 2: Server rebinds to same port and accepts new connection
        server_sock_2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock_2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock_2.bind(("127.0.0.1", port))
        server_sock_2.listen(1)

        conn_2, _ = server_sock_2.accept()
        conn_2.sendall(pack_message(MSG_VIDEO, b"FRAME_AFTER_RECONNECT"))
        time.sleep(0.05)

        with client._lock:
            self.assertGreaterEqual(client.connected_count, 2)
            self.assertIn(b"FRAME_BEFORE_DISCONNECT", client.received_videos)
            self.assertIn(b"FRAME_AFTER_RECONNECT", client.received_videos)

        conn_2.close()
        server_sock_2.close()
        client.stop()


if __name__ == "__main__":
    unittest.main()
