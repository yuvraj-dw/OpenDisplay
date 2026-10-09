import unittest
from unittest.mock import MagicMock, patch
from server.transport.winusb_transport import WinUsbTransport

class TestWinUsbTransport(unittest.TestCase):
    def test_packet_framing(self):
        transport = WinUsbTransport()
        frame = transport.frame_packet(0x02, b"\x00\x00\x00\x01\x65")
        self.assertEqual(frame, b"\x00\x00\x00\x06\x02\x00\x00\x00\x01\x65")

    def test_unframe_packet(self):
        transport = WinUsbTransport()
        raw = b"\x00\x00\x00\x06\x02\x00\x00\x00\x01\x65"
        msg_type, payload = transport.unframe_packet(raw)
        self.assertEqual(msg_type, 0x02)
        self.assertEqual(payload, b"\x00\x00\x00\x01\x65")

    def test_unframe_short_packet_raises(self):
        transport = WinUsbTransport()
        with self.assertRaises(ValueError):
            transport.unframe_packet(b"\x00\x00\x01")

    def test_send_packet_when_not_connected(self):
        transport = WinUsbTransport()
        transport.is_connected = False
        self.assertFalse(transport.send_packet(0x02, b"test"))

    def test_read_packet_when_not_connected(self):
        transport = WinUsbTransport()
        transport.is_connected = False
        self.assertIsNone(transport.read_packet())

    def test_send_packet_mocked(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 12345
        mock_winusb = MagicMock()

        def fake_write_pipe(h, pipe, data, length, written_ptr, overlapped):
            written_ptr._obj.value = length
            return 1

        mock_winusb.WinUsb_WritePipe.side_effect = fake_write_pipe
        transport._winusb = mock_winusb

        success = transport.send_packet(0x02, b"hello")
        self.assertTrue(success)
        mock_winusb.WinUsb_WritePipe.assert_called_once()

    def test_read_packet_mocked(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 12345
        mock_winusb = MagicMock()

        framed = transport.frame_packet(0x04, b"touch_event")

        def fake_read_pipe(h, pipe, buf, buf_len, transferred_ptr, overlapped):
            buf.raw = framed + b"\x00" * (buf_len - len(framed))
            transferred_ptr._obj.value = len(framed)
            return 1

        mock_winusb.WinUsb_ReadPipe.side_effect = fake_read_pipe
        transport._winusb = mock_winusb

        result = transport.read_packet()
        self.assertIsNotNone(result)
        msg_type, payload = result
        self.assertEqual(msg_type, 0x04)
        self.assertEqual(payload, b"touch_event")

    def test_read_packet_framed_touch_0x04(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 12345
        mock_winusb = MagicMock()

        framed = transport.frame_packet(0x04, b"m:move:0.2500:0.7500\n")

        def fake_read_pipe(h, pipe, buf, buf_len, transferred_ptr, overlapped):
            buf.raw = framed + b"\x00" * (buf_len - len(framed))
            transferred_ptr._obj.value = len(framed)
            return 1

        mock_winusb.WinUsb_ReadPipe.side_effect = fake_read_pipe
        transport._winusb = mock_winusb

        result = transport.read_packet()
        self.assertIsNotNone(result)
        msg_type, payload = result
        self.assertEqual(msg_type, 0x04)
        self.assertEqual(payload, b"m:move:0.2500:0.7500\n")

    def test_read_packet_raw_touch_starts_with_m(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 12345
        mock_winusb = MagicMock()

        raw_touch = b"m:down:0.1234:0.5678\n"

        def fake_read_pipe(h, pipe, buf, buf_len, transferred_ptr, overlapped):
            buf.raw = raw_touch + b"\x00" * (buf_len - len(raw_touch))
            transferred_ptr._obj.value = len(raw_touch)
            return 1

        mock_winusb.WinUsb_ReadPipe.side_effect = fake_read_pipe
        transport._winusb = mock_winusb

        result = transport.read_packet()
        self.assertIsNotNone(result)
        msg_type, payload = result
        self.assertEqual(msg_type, 0x04)
        self.assertEqual(payload, raw_touch)

    def test_send_packet_disconnect_cleanup(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 0x200
        transport.handle = 0x100
        mock_winusb = MagicMock()
        mock_kernel32 = MagicMock()

        mock_winusb.WinUsb_WritePipe.return_value = 0
        mock_kernel32.GetLastError.return_value = 1167  # ERROR_DEVICE_NOT_CONNECTED

        transport._winusb = mock_winusb
        transport._kernel32 = mock_kernel32

        success = transport.send_packet(0x02, b"test_payload")
        self.assertFalse(success)
        self.assertFalse(transport.is_connected)
        self.assertIsNone(transport.winusb_handle)
        self.assertIsNone(transport.handle)
        mock_winusb.WinUsb_Free.assert_called_once_with(0x200)
        mock_kernel32.CloseHandle.assert_called_once_with(0x100)

    def test_read_packet_disconnect_cleanup(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 0x200
        transport.handle = 0x100
        mock_winusb = MagicMock()
        mock_kernel32 = MagicMock()

        mock_winusb.WinUsb_ReadPipe.return_value = 0
        mock_kernel32.GetLastError.return_value = 31  # ERROR_GEN_FAILURE

        transport._winusb = mock_winusb
        transport._kernel32 = mock_kernel32

        result = transport.read_packet()
        self.assertIsNone(result)
        self.assertFalse(transport.is_connected)
        self.assertIsNone(transport.winusb_handle)
        self.assertIsNone(transport.handle)

    def test_read_packet_timeout_retains_connection(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.winusb_handle = 0x200
        transport.handle = 0x100
        mock_winusb = MagicMock()
        mock_kernel32 = MagicMock()

        mock_winusb.WinUsb_ReadPipe.return_value = 0
        mock_kernel32.GetLastError.return_value = 121  # ERROR_SEM_TIMEOUT

        transport._winusb = mock_winusb
        transport._kernel32 = mock_kernel32

        result = transport.read_packet()
        self.assertIsNone(result)
        self.assertTrue(transport.is_connected)
        self.assertEqual(transport.winusb_handle, 0x200)

    def test_open_device_sets_pipe_policies(self):
        transport = WinUsbTransport()
        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = 0x100
        mock_winusb = MagicMock()
        mock_winusb.WinUsb_Initialize.return_value = 1

        transport._kernel32 = mock_kernel32
        transport._winusb = mock_winusb

        success = transport.open_device("\\\\?\\usb#device")
        self.assertTrue(success)
        self.assertEqual(mock_winusb.WinUsb_SetPipePolicy.call_count, 2)

    def test_open_device_mocked_success(self):
        transport = WinUsbTransport()
        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = 0x100
        mock_winusb = MagicMock()
        mock_winusb.WinUsb_Initialize.return_value = 1

        transport._kernel32 = mock_kernel32
        transport._winusb = mock_winusb

        success = transport.open_device("\\\\?\\usb#device")
        self.assertTrue(success)
        self.assertTrue(transport.is_connected)
        self.assertEqual(transport.handle, 0x100)

    def test_open_device_mocked_failure_create_file(self):
        transport = WinUsbTransport()
        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = 0
        transport._kernel32 = mock_kernel32
        transport._winusb = MagicMock()

        success = transport.open_device("\\\\?\\usb#device")
        self.assertFalse(success)
        self.assertFalse(transport.is_connected)

    def test_close_frees_resources(self):
        transport = WinUsbTransport()
        transport.is_connected = True
        transport.handle = 0x100
        transport.winusb_handle = 0x200
        mock_kernel32 = MagicMock()
        mock_winusb = MagicMock()
        transport._kernel32 = mock_kernel32
        transport._winusb = mock_winusb

        transport.close()
        self.assertFalse(transport.is_connected)
        self.assertIsNone(transport.handle)
        self.assertIsNone(transport.winusb_handle)
        mock_winusb.WinUsb_Free.assert_called_once_with(0x200)
        mock_kernel32.CloseHandle.assert_called_once_with(0x100)

    def test_switch_aoap(self):
        transport = WinUsbTransport()
        self.assertFalse(transport.switch_aoap(0x18D1, 0x2D00))

    def test_find_devices_no_devices(self):
        transport = WinUsbTransport()
        devices = transport.find_devices()
        self.assertIsInstance(devices, list)

if __name__ == '__main__':
    unittest.main()
