import ctypes
from ctypes import wintypes
import logging
import os
import struct

logger = logging.getLogger("OpenDisplay.WinUSB")

OPENDISPLAY_AOAP_GUID = "{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}"

# Pipe policy constants
PIPE_TRANSFER_TIMEOUT = 0x03
RAW_IO = 0x07

# Windows error constants
ERROR_INVALID_HANDLE = 6
ERROR_GEN_FAILURE = 31
ERROR_SEM_TIMEOUT = 121
ERROR_OPERATION_ABORTED = 995
ERROR_DEVICE_NOT_CONNECTED = 1167

DISCONNECT_ERRORS = (
    ERROR_DEVICE_NOT_CONNECTED,
    ERROR_GEN_FAILURE,
    ERROR_INVALID_HANDLE,
    ERROR_OPERATION_ABORTED,
)


class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', ctypes.c_ubyte * 8)
    ]

    @classmethod
    def from_str(cls, s: str):
        import uuid
        u = uuid.UUID(s)
        g = cls()
        g.Data1 = u.time_low
        g.Data2 = u.time_mid
        g.Data3 = u.time_hi_version
        for i, b in enumerate(u.bytes[8:]):
            g.Data4[i] = b
        return g


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('InterfaceClassGuid', GUID),
        ('Flags', wintypes.DWORD),
        ('Reserved', ctypes.c_void_p)
    ]


class WinUsbTransport:
    def __init__(self):
        self.handle = None
        self.winusb_handle = None
        self.out_pipe = 0x02
        self.in_pipe = 0x81
        self.is_connected = False
        self._setupapi = None
        self._winusb = None
        self._kernel32 = None
        self._init_dlls()

    def _init_dlls(self):
        if os.name == 'nt':
            try:
                self._kernel32 = ctypes.windll.kernel32
                self._kernel32.CreateFileW.restype = ctypes.c_void_p
                self._kernel32.CreateFileW.argtypes = [
                    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p
                ]
                self._kernel32.CloseHandle.restype = wintypes.BOOL
                self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

                self._setupapi = ctypes.windll.setupapi
                self._setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
                self._setupapi.SetupDiGetClassDevsW.argtypes = [
                    ctypes.c_void_p, wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD
                ]
                self._setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
                self._setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
                    ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID),
                    wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
                ]
                self._setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
                self._setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
                ]
                self._setupapi.SetupDiDestroyDeviceInfoList.restype = wintypes.BOOL
                self._setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]

                self._winusb = ctypes.windll.winusb
                self._winusb.WinUsb_Initialize.restype = wintypes.BOOL
                self._winusb.WinUsb_Initialize.argtypes = [
                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
                ]
                self._winusb.WinUsb_Free.restype = wintypes.BOOL
                self._winusb.WinUsb_Free.argtypes = [ctypes.c_void_p]
                self._winusb.WinUsb_WritePipe.restype = wintypes.BOOL
                self._winusb.WinUsb_WritePipe.argtypes = [
                    ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p,
                    wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p
                ]
                self._winusb.WinUsb_ReadPipe.restype = wintypes.BOOL
                self._winusb.WinUsb_ReadPipe.argtypes = [
                    ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p,
                    wintypes.ULONG, ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p
                ]
                self._winusb.WinUsb_SetPipePolicy.restype = wintypes.BOOL
                self._winusb.WinUsb_SetPipePolicy.argtypes = [
                    ctypes.c_void_p, ctypes.c_ubyte, wintypes.ULONG,
                    wintypes.ULONG, ctypes.c_void_p
                ]
            except Exception as e:
                logger.warning(f"Failed to load WinUSB DLLs: {e}")

    @staticmethod
    def frame_packet(msg_type: int, payload: bytes) -> bytes:
        total_len = 1 + len(payload)
        return struct.pack('>IB', total_len, msg_type) + bytes(payload)

    @staticmethod
    def unframe_packet(raw_bytes: bytes) -> tuple[int, bytes]:
        if len(raw_bytes) < 5:
            raise ValueError("Packet too short")
        total_len, msg_type = struct.unpack('>IB', raw_bytes[:5])
        payload = raw_bytes[5:4 + total_len]
        return msg_type, payload

    def find_devices(self) -> list[str]:
        if not self._setupapi:
            return []
        guid = GUID.from_str(OPENDISPLAY_AOAP_GUID)
        DIGCF_PRESENT = 0x02
        DIGCF_DEVICEINTERFACE = 0x10
        hdev = self._setupapi.SetupDiGetClassDevsW(
            ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if not hdev or hdev == invalid_handle:
            return []

        devices = []
        try:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(iface)
            idx = 0
            while self._setupapi.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid), idx, ctypes.byref(iface)):
                req_size = wintypes.DWORD(0)
                self._setupapi.SetupDiGetDeviceInterfaceDetailW(
                    hdev, ctypes.byref(iface), None, 0, ctypes.byref(req_size), None
                )
                if req_size.value > 0:
                    detail_buf = ctypes.create_string_buffer(req_size.value)
                    cb_size = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 5
                    struct.pack_into('I', detail_buf, 0, cb_size)
                    if self._setupapi.SetupDiGetDeviceInterfaceDetailW(
                        hdev, ctypes.byref(iface), detail_buf, req_size.value, None, None
                    ):
                        path = ctypes.wstring_at(ctypes.addressof(detail_buf) + 4)
                        devices.append(path)
                idx += 1
        finally:
            self._setupapi.SetupDiDestroyDeviceInfoList(hdev)
        return devices

    def open_device(self, path: str) -> bool:
        if not self._winusb or not self._kernel32 or not path:
            return False
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        FILE_SHARE_READ = 0x01
        FILE_SHARE_WRITE = 0x02
        OPEN_EXISTING = 3
        FILE_FLAG_OVERLAPPED = 0x40000000
        invalid_handle = ctypes.c_void_p(-1).value

        handle = self._kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            None
        )
        if not handle or handle == invalid_handle:
            logger.warning(f"Failed to open device handle for {path}")
            return False

        self.handle = handle

        h_winusb = ctypes.c_void_p()
        if not self._winusb.WinUsb_Initialize(self.handle, ctypes.byref(h_winusb)):
            logger.warning("WinUsb_Initialize failed")
            self._kernel32.CloseHandle(self.handle)
            self.handle = None
            return False

        self.winusb_handle = h_winusb
        self.is_connected = True

        # Configure WinUSB pipe policies
        try:
            timeout = wintypes.ULONG(1000)
            self._winusb.WinUsb_SetPipePolicy(
                self.winusb_handle,
                ctypes.c_ubyte(self.in_pipe),
                PIPE_TRANSFER_TIMEOUT,
                ctypes.sizeof(timeout),
                ctypes.byref(timeout)
            )
            raw_io = ctypes.c_ubyte(1)
            self._winusb.WinUsb_SetPipePolicy(
                self.winusb_handle,
                ctypes.c_ubyte(self.out_pipe),
                RAW_IO,
                ctypes.sizeof(raw_io),
                ctypes.byref(raw_io)
            )
        except Exception as e:
            logger.warning(f"Failed to set WinUSB pipe policies: {e}")

        logger.info(f"WinUSB device opened successfully: {path}")
        return True

    def _get_last_error(self) -> int:
        try:
            if self._kernel32 and hasattr(self._kernel32, 'GetLastError'):
                return int(self._kernel32.GetLastError())
            if os.name == 'nt' and hasattr(ctypes, 'windll') and hasattr(ctypes.windll, 'kernel32'):
                return int(ctypes.windll.kernel32.GetLastError())
        except Exception:
            pass
        return 0

    def send_packet(self, msg_type: int, payload: bytes) -> bool:
        if not self.is_connected or not self.winusb_handle or not self._winusb:
            return False
        data = self.frame_packet(msg_type, payload)
        written = wintypes.DWORD(0)
        res = self._winusb.WinUsb_WritePipe(
            self.winusb_handle,
            ctypes.c_ubyte(self.out_pipe),
            data,
            len(data),
            ctypes.byref(written),
            None
        )
        if not res or written.value != len(data):
            err = self._get_last_error()
            if err in DISCONNECT_ERRORS:
                logger.warning(f"WinUSB write failed (error {err}): device disconnected. Closing transport.")
                self.close()
            return False
        return True

    def read_packet(self, timeout_ms: int = 1000) -> tuple[int, bytes] | None:
        if not self.is_connected or not self.winusb_handle or not self._winusb:
            return None
        buf = ctypes.create_string_buffer(4096)
        transferred = wintypes.DWORD(0)
        res = self._winusb.WinUsb_ReadPipe(
            self.winusb_handle,
            ctypes.c_ubyte(self.in_pipe),
            buf,
            4096,
            ctypes.byref(transferred),
            None
        )
        if not res:
            err = self._get_last_error()
            if err == ERROR_SEM_TIMEOUT:
                return None
            if err in DISCONNECT_ERRORS:
                logger.warning(f"WinUSB read failed (error {err}): device disconnected. Closing transport.")
                self.close()
            return None

        if transferred.value > 0:
            raw_data = buf.raw[:transferred.value]
            if raw_data.startswith(b"m:"):
                return 0x04, raw_data
            if transferred.value >= 5:
                try:
                    return self.unframe_packet(raw_data)
                except ValueError:
                    return None
        return None

    def switch_aoap(self, vendor_id: int = 0, product_id: int = 0) -> bool:
        """
        Attempt to switch device to AOAP accessory mode via USB control transfer.
        """
        logger.debug(f"switch_aoap called for VID={vendor_id:#06x} PID={product_id:#06x}")
        return False

    def close(self):
        self.is_connected = False
        invalid_handle = ctypes.c_void_p(-1).value
        if self.winusb_handle and self._winusb:
            try:
                self._winusb.WinUsb_Free(self.winusb_handle)
            except Exception as e:
                logger.warning(f"Error freeing WinUSB handle: {e}")
            self.winusb_handle = None
        if self.handle and self.handle != invalid_handle and self._kernel32:
            try:
                self._kernel32.CloseHandle(self.handle)
            except Exception as e:
                logger.warning(f"Error closing device handle: {e}")
            self.handle = None
