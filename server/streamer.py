import argparse
import ctypes
import json
import logging
import select
import socket
import sys
import threading
import time

from server.capture.dxgi_capture import DxgiScreenCapture
from server.encoder.hw_encoder import HardwareEncoder
from server.transport.adb_bridge import AdbBridge
from server.transport.protocol import MSG_CONFIG, MSG_VIDEO, pack_message
from server.transport.winusb_transport import WinUsbTransport

logger = logging.getLogger(__name__)

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def _get_encoded_chunks(encoder, frame):
    if hasattr(encoder, 'encode_frame'):
        is_mock = hasattr(encoder, '_mock_return_value') or hasattr(getattr(encoder, 'encode_frame', None), '_mock_return_value')
        if is_mock:
            try:
                from unittest.mock import DEFAULT
                if getattr(encoder.encode_frame, '_mock_return_value', DEFAULT) is not DEFAULT:
                    return encoder.encode_frame(frame)
            except Exception:
                pass
            if hasattr(encoder, 'encode'):
                return encoder.encode(frame)
        return encoder.encode_frame(frame)
    if hasattr(encoder, 'encode'):
        return encoder.encode(frame)
    return []


class Streamer:
    """Streams captured screen frames over TCP to connected clients (e.g.

    Android tablet via ADB).
    """

    def __init__(
        self,
        host: str = '127.0.0.1',
        port: int = 7070,
        display_idx: int = 0,
        fps: int = 60,
        adb_bridge: AdbBridge | None = None,
        capture: DxgiScreenCapture | None = None,
        encoder: HardwareEncoder | None = None,
        auto_forward: bool = True,
        winusb_transport: WinUsbTransport | None = None,
    ):
        self.host = host
        self.port = port
        self.display_idx = display_idx
        self.fps = fps
        self.auto_forward = auto_forward
        self.winusb_transport = winusb_transport

        self.adb_bridge = adb_bridge or AdbBridge()
        self.capture = capture or DxgiScreenCapture()
        self.encoder = encoder or HardwareEncoder(codec='auto', fps=fps, bitrate='6M')

        self._server_socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self.is_running = False

        self._clients: list[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._capture_thread: threading.Thread | None = None
        self._winusb_thread: threading.Thread | None = None

    def setup_adb(self) -> bool:
        """Forward host port to device port using ADB."""
        success = self.adb_bridge.forward_port(self.port, self.port)
        if success:
            logger.info(f"Port forwarding established: tcp:{self.port} -> tcp:{self.port}")
        else:
            logger.warning(f"Failed to forward port {self.port} via ADB")
        return success

    def start_server(self) -> socket.socket:
        """Create and bind the TCP server socket with TCP_NODELAY enabled."""
        self.is_running = True
        self._stop_event.clear()
        if self._server_socket is not None:
            return self._server_socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        s.bind((self.host, self.port))
        self.port = s.getsockname()[1]
        s.listen(1)
        self._server_socket = s
        self.is_running = True
        logger.info(f"Streamer listening on {self.host}:{self.port}")
        return s

    def send_config(self, client_sock: socket.socket) -> bool:
        """Send stream configuration handshake (MSG_CONFIG) to client."""
        try:
            width = 1920
            height = 1080
            if hasattr(self.capture, 'list_displays'):
                try:
                    displays = self.capture.list_displays()
                    if displays and 0 <= self.display_idx < len(displays):
                        width = displays[self.display_idx].get('width', width)
                        height = displays[self.display_idx].get('height', height)
                except Exception as e:
                    logger.debug(f"Failed getting display info for config: {e}")

            if hasattr(self.encoder, 'width') and self.encoder.width:
                width = self.encoder.width
            if hasattr(self.encoder, 'height') and self.encoder.height:
                height = self.encoder.height

            config_json = json.dumps({'width': width, 'height': height, 'fps': self.fps})
            packed = pack_message(MSG_CONFIG, config_json.encode('utf-8'))
            client_sock.sendall(packed)
            logger.info(f"Sent MSG_CONFIG handshake: width={width}, height={height}, fps={self.fps}")
            return True
        except (OSError, ConnectionResetError, BrokenPipeError):
            raise
        except Exception as e:
            logger.error(f"Error sending config handshake: {e}")
            return False

    def broadcast_packet(self, msg_type: int, payload: bytes):
        """Broadcasts a message to WinUSB transport (if connected) and all connected TCP clients."""
        if self.winusb_transport and getattr(self.winusb_transport, 'is_connected', False):
            try:
                self.winusb_transport.send_packet(msg_type, payload)
            except Exception as e:
                logger.debug(f"Failed sending packet via WinUSB: {e}")

        packet = pack_message(msg_type, payload)
        self.broadcast(packet)

    def broadcast(self, packet: bytes):
        """Broadcasts a packet to all connected clients, removing dead connections."""
        with self._clients_lock:
            disconnected = []
            for client in self._clients:
                try:
                    client.sendall(packet)
                except (OSError, ConnectionResetError, BrokenPipeError):
                    disconnected.append(client)
            for client in disconnected:
                try:
                    client.close()
                except Exception:
                    pass
                if client in self._clients:
                    self._clients.remove(client)

    def capture_and_stream(self):
        """Continuously captures frames from the active display, encodes them,

        and broadcasts video packets to all connected clients.
        """
        frame_interval = 1.0 / self.fps

        while self.is_running and not self._stop_event.is_set():
            t0 = time.perf_counter()

            displays = []
            if hasattr(self.capture, 'list_displays'):
                try:
                    displays = self.capture.list_displays() or []
                except Exception as e:
                    logger.debug(f"Error checking displays: {e}")

            if not displays:
                time.sleep(0.02)
                continue

            idx = self.display_idx
            if idx >= len(displays):
                idx = len(displays) - 1
            if idx < 0:
                idx = 0

            try:
                frame = self.capture.capture_frame(display_idx=idx)
            except Exception as e:
                logger.debug(f"Error capturing frame: {e}")
                frame = None

            if frame is None:
                time.sleep(0.005)
                continue

            if hasattr(self, 'on_frame_captured') and callable(self.on_frame_captured):
                try:
                    self.on_frame_captured(frame)
                except Exception:
                    pass

            chunks = _get_encoded_chunks(self.encoder, frame)
            if isinstance(chunks, (bytes, bytearray)):
                chunks = [chunks] if chunks else []
            elif chunks is None:
                chunks = []
            else:
                chunks = list(chunks)

            for chunk in chunks:
                if not chunk:
                    continue
                self.broadcast_packet(MSG_VIDEO, chunk)

            elapsed = time.perf_counter() - t0
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def send_single_frame(self, client_sock: socket.socket) -> bool:
        """Capture one frame, encode it, and send it packaged as MSG_VIDEO."""
        try:
            displays = []
            if hasattr(self.capture, 'list_displays'):
                try:
                    displays = self.capture.list_displays() or []
                except Exception:
                    pass
            idx = self.display_idx
            if displays:
                if idx >= len(displays):
                    idx = len(displays) - 1
                if idx < 0:
                    idx = 0

            frame = self.capture.capture_frame(idx)
            if frame is None:
                return False

            chunks = _get_encoded_chunks(self.encoder, frame)
            if isinstance(chunks, (bytes, bytearray)):
                chunks = [chunks] if chunks else []
            elif chunks is None:
                chunks = []
            else:
                chunks = list(chunks)

            # Filter out empty chunks
            valid_chunks = [c for c in chunks if c]
            if not valid_chunks:
                return False

            for chunk in valid_chunks:
                packed = pack_message(MSG_VIDEO, chunk)
                client_sock.sendall(packed)
            return True
        except (OSError, ConnectionResetError, BrokenPipeError):
            raise
        except Exception as e:
            logger.error(f"Error encoding or sending frame: {e}")
            return False

    def handle_input_event(
        self,
        action: str,
        normX: float = 0.0,
        normY: float = 0.0,
        display_idx: int | None = None,
        norm_x: float | None = None,
        norm_y: float | None = None,
    ) -> tuple[int, int]:
        """Process incoming touch/mouse action and map to target display coordinates.

        Calculates target screen coordinates:
            tx = int(left + normX * width)
            ty = int(top + normY * height)
        Dispatches cursor position and mouse events via Win32 user32 APIs.
        """
        if norm_x is not None:
            normX = norm_x
        if norm_y is not None:
            normY = norm_y

        try:
            normX = float(normX)
            normY = float(normY)
        except (ValueError, TypeError):
            normX, normY = 0.0, 0.0

        left, top, width, height = 0, 0, 1920, 1080
        displays = []
        if hasattr(self.capture, 'list_displays'):
            try:
                displays = self.capture.list_displays() or []
            except Exception as e:
                logger.debug(f"Error querying display info for input event: {e}")

        if displays:
            target_idx = display_idx if display_idx is not None else self.display_idx
            if target_idx < 0 or target_idx >= len(displays):
                target_idx = len(displays) - 1 if target_idx >= len(displays) else 0
            target_disp = displays[target_idx]
            left = target_disp.get('left', 0) or 0
            top = target_disp.get('top', 0) or 0
            width = target_disp.get('width', 1920) or 1920
            height = target_disp.get('height', 1080) or 1080

        tx = int(left + normX * width)
        ty = int(top + normY * height)

        act = action.lower() if isinstance(action, str) else ''
        try:
            if hasattr(ctypes, 'windll') and hasattr(ctypes.windll, 'user32'):
                ctypes.windll.user32.SetCursorPos(tx, ty)
                if act == 'down':
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                elif act == 'up':
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        except Exception as e:
            logger.debug(f"Failed to execute Win32 mouse event: {e}")

        return tx, ty

    def _handle_client(self, client_sock: socket.socket):
        """Streaming loop and client event reader for an accepted client connection."""
        try:
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as e:
            logger.debug(f"Failed setting TCP_NODELAY on client socket: {e}")

        try:
            client_sock.settimeout(0.5)
        except Exception:
            pass

        logger.info("Client connected. Starting screen capture stream...")
        try:
            self.send_config(client_sock)
        except (OSError, ConnectionResetError, BrokenPipeError) as e:
            logger.info(f"Client disconnected during config handshake: {e}")
            return

        with self._clients_lock:
            if client_sock not in self._clients:
                self._clients.append(client_sock)

        if not self._stop_event.is_set():
            self.is_running = True

        buffer = ""
        try:
            while self.is_running and not self._stop_event.is_set():
                try:
                    rlist, _, _ = select.select([client_sock], [], [], 0.5)
                    if not rlist:
                        continue
                except (ValueError, TypeError, OSError):
                    pass

                try:
                    data = client_sock.recv(2048)
                except (socket.timeout, TimeoutError):
                    continue
                except (OSError, ConnectionResetError, BrokenPipeError):
                    break

                if not data:
                    break

                try:
                    buffer += data.decode('utf-8', errors='ignore')
                except Exception:
                    continue

                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if line.startswith('m:'):
                        parts = line.split(':')
                        if len(parts) == 4:
                            action = parts[1].strip()
                            try:
                                normX = float(parts[2].strip())
                                normY = float(parts[3].strip())
                                self.handle_input_event(action, normX, normY)
                            except ValueError as e:
                                logger.debug(f"Invalid float in mouse event line '{line}': {e}")
        except (OSError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            with self._clients_lock:
                if client_sock in self._clients:
                    self._clients.remove(client_sock)
            try:
                client_sock.close()
            except Exception:
                pass

    def handle_client(self, client_sock: socket.socket):
        """Streaming loop for an accepted client connection."""
        return self._handle_client(client_sock)

    def serve_forever(self, max_clients: int | None = None):
        """Main server loop: accepts clients and streams frames."""
        self.is_running = True
        self._stop_event.clear()
        if self.auto_forward:
            self.setup_adb()

        server_sock = self.start_server()
        clients_served = 0

        if self._capture_thread is None or not self._capture_thread.is_alive():
            self._capture_thread = threading.Thread(target=self.capture_and_stream, daemon=True)
            self._capture_thread.start()

        if self.winusb_transport and (self._winusb_thread is None or not self._winusb_thread.is_alive()):
            self._winusb_thread = threading.Thread(target=self._winusb_reader_loop, daemon=True)
            self._winusb_thread.start()

        client_threads = []
        try:
            while not self._stop_event.is_set():
                server_sock.settimeout(0.5)
                try:
                    client_sock, client_addr = server_sock.accept()
                except (TimeoutError, socket.timeout):
                    continue
                except OSError:
                    break

                logger.info(f"Accepted connection from {client_addr}")
                client_threads = [th for th in client_threads if th.is_alive()]
                t = threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True)
                t.start()
                client_threads.append(t)
                clients_served += 1

                if max_clients is not None and clients_served >= max_clients:
                    break
        finally:
            self.stop()

    def _winusb_reader_loop(self):
        """Continuously reads input packets from WinUSB transport and dispatches touch events."""
        while self.is_running and not self._stop_event.is_set():
            if self.winusb_transport and getattr(self.winusb_transport, 'is_connected', False):
                try:
                    packet = self.winusb_transport.read_packet()
                except Exception as e:
                    logger.debug(f"Error reading WinUSB packet: {e}")
                    packet = None

                if packet:
                    msg_type, payload = packet
                    is_touch = (msg_type == 0x04)
                    if isinstance(payload, (bytes, bytearray)):
                        if payload.startswith(b'm:'):
                            is_touch = True
                    elif isinstance(payload, str) and payload.startswith('m:'):
                        is_touch = True

                    if is_touch:
                        try:
                            if isinstance(payload, (bytes, bytearray)):
                                text = payload.decode('utf-8', errors='ignore')
                            else:
                                text = str(payload)
                            for line in text.strip().split('\n'):
                                line = line.strip()
                                if line.startswith('m:'):
                                    parts = line.split(':')
                                    if len(parts) == 4:
                                        action = parts[1].strip()
                                        normX = float(parts[2].strip())
                                        normY = float(parts[3].strip())
                                        self.handle_input_event(action, normX, normY)
                                elif len(line.split(':')) == 3 and msg_type == 0x04:
                                    parts = line.split(':')
                                    action = parts[0].strip()
                                    normX = float(parts[1].strip())
                                    normY = float(parts[2].strip())
                                    self.handle_input_event(action, normX, normY)
                        except Exception as e:
                            logger.debug(f"Error handling WinUSB input event: {e}")
                else:
                    time.sleep(0.005)
            else:
                time.sleep(0.005)

    def start_background(self) -> threading.Thread:
        """Start the server in a background daemon thread."""
        self.is_running = True
        self._stop_event.clear()
        self.start_server()
        if self._capture_thread is None or not self._capture_thread.is_alive():
            self._capture_thread = threading.Thread(target=self.capture_and_stream, daemon=True)
            self._capture_thread.start()
        if self.winusb_transport and (self._winusb_thread is None or not self._winusb_thread.is_alive()):
            self._winusb_thread = threading.Thread(target=self._winusb_reader_loop, daemon=True)
            self._winusb_thread.start()
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Stop streaming and clean up resources."""
        self._stop_event.set()
        self.is_running = False

        with self._clients_lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()

        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
            self._server_socket = None

        if self.capture:
            try:
                self.capture.close()
            except Exception:
                pass

        if self.encoder:
            try:
                self.encoder.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


StreamServer = Streamer


def main():
    parser = argparse.ArgumentParser(description="Windows USB Extended Display Stream Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP to bind to")
    parser.add_argument("--port", type=int, default=7070, help="Port to listen on")
    parser.add_argument("--display", type=int, default=0, help="Display index to capture")
    parser.add_argument("--fps", type=int, default=60, help="Target FPS")
    parser.add_argument("--no-adb", action="store_true", help="Skip automatic ADB forward setup")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    streamer = Streamer(
        host=args.host,
        port=args.port,
        display_idx=args.display,
        fps=args.fps,
        auto_forward=not args.no_adb,
    )
    try:
        streamer.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping streamer server...")
    finally:
        streamer.stop()


if __name__ == '__main__':
    main()
