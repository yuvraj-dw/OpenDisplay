import argparse
import json
import logging
import socket
import threading
import time

from server.capture.dxgi_capture import DxgiScreenCapture
from server.encoder.hw_encoder import HardwareEncoder
from server.transport.adb_bridge import AdbBridge
from server.transport.protocol import MSG_CONFIG, MSG_VIDEO, pack_message

logger = logging.getLogger(__name__)


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
    ):
        self.host = host
        self.port = port
        self.display_idx = display_idx
        self.fps = fps
        self.auto_forward = auto_forward

        self.adb_bridge = adb_bridge or AdbBridge()
        self.capture = capture or DxgiScreenCapture()
        self.encoder = encoder or HardwareEncoder(fps=fps)

        self._server_socket: socket.socket | None = None
        self._stop_event = threading.Event()
        self.is_running = False

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

    def send_single_frame(self, client_sock: socket.socket) -> bool:
        """Capture one frame, encode it, and send it packaged as MSG_VIDEO."""
        try:
            frame = self.capture.capture_frame(self.display_idx)
            if frame is None:
                return False

            frame_data = self.encoder.encode(frame)
            if not frame_data:
                return False

            packed = pack_message(MSG_VIDEO, frame_data)
            client_sock.sendall(packed)
            return True
        except (OSError, ConnectionResetError, BrokenPipeError):
            raise
        except Exception as e:
            logger.error(f"Error encoding or sending frame: {e}")
            return False

    def handle_client(self, client_sock: socket.socket):
        """Streaming loop for an accepted client connection."""
        try:
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception as e:
            logger.debug(f"Failed setting TCP_NODELAY on client socket: {e}")

        logger.info("Client connected. Starting screen capture stream...")
        try:
            self.send_config(client_sock)
        except (OSError, ConnectionResetError, BrokenPipeError) as e:
            logger.info(f"Client disconnected during config handshake: {e}")
            return

        frame_interval = 1.0 / self.fps

        while self.is_running and not self._stop_event.is_set():
            t0 = time.perf_counter()
            try:
                sent = self.send_single_frame(client_sock)
                if not sent:
                    time.sleep(0.005)
                    continue
            except (OSError, ConnectionResetError, BrokenPipeError) as e:
                logger.info(f"Client disconnected: {e}")
                break

            elapsed = time.perf_counter() - t0
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def serve_forever(self, max_clients: int | None = None):
        """Main server loop: accepts clients and streams frames."""
        if self.auto_forward:
            self.setup_adb()

        server_sock = self.start_server()
        clients_served = 0

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
                try:
                    self.handle_client(client_sock)
                finally:
                    try:
                        client_sock.close()
                    except Exception:
                        pass
                    clients_served += 1

                if max_clients is not None and clients_served >= max_clients:
                    break
        finally:
            self.stop()

    def start_background(self) -> threading.Thread:
        """Start the server in a background daemon thread."""
        self.start_server()
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Stop streaming and clean up resources."""
        self._stop_event.set()
        self.is_running = False
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
