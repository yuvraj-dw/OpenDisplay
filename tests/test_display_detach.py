import unittest
from unittest.mock import MagicMock, patch
import win32con

from opendisplay_server import attach_virtual_display, detach_virtual_display


class TestVirtualDisplayAttachDetach(unittest.TestCase):
    @patch('win32api.EnumDisplayDevices')
    @patch('win32api.EnumDisplaySettings')
    @patch('win32api.ChangeDisplaySettingsEx')
    def test_detach_virtual_display_modifies_settings(self, mock_change, mock_settings, mock_devices):
        dev_primary = MagicMock()
        dev_primary.DeviceName = r"\\.\DISPLAY1"
        dev_primary.DeviceString = "Intel(R) UHD Graphics"
        dev_primary.StateFlags = win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP | win32con.DISPLAY_DEVICE_PRIMARY_DEVICE

        dev_virtual = MagicMock()
        dev_virtual.DeviceName = r"\\.\DISPLAY25"
        dev_virtual.DeviceString = "Virtual Display Driver"
        dev_virtual.StateFlags = win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP

        mock_devices.side_effect = [dev_primary, dev_virtual] + [Exception()] * 38

        dm = MagicMock()
        dm.PelsWidth = 1280
        dm.PelsHeight = 800
        mock_settings.return_value = dm

        detach_virtual_display()

        # Check dm was set to 0x0
        self.assertEqual(dm.PelsWidth, 0)
        self.assertEqual(dm.PelsHeight, 0)
        mock_change.assert_any_call(
            r"\\.\DISPLAY25", dm, win32con.CDS_UPDATEREGISTRY | win32con.CDS_NORESET
        )
        mock_change.assert_any_call(None, None, 0)

    @patch('win32api.EnumDisplayDevices')
    @patch('win32api.EnumDisplaySettings')
    @patch('win32api.ChangeDisplaySettingsEx')
    def test_attach_virtual_display_positions_monitor(self, mock_change, mock_settings, mock_devices):
        dev_primary = MagicMock()
        dev_primary.DeviceName = r"\\.\DISPLAY1"
        dev_primary.DeviceString = "Intel(R) UHD Graphics"
        dev_primary.StateFlags = win32con.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP | win32con.DISPLAY_DEVICE_PRIMARY_DEVICE

        dev_virtual = MagicMock()
        dev_virtual.DeviceName = r"\\.\DISPLAY25"
        dev_virtual.DeviceString = "Virtual Display Driver"
        dev_virtual.StateFlags = 0  # Detached

        mock_devices.side_effect = [dev_primary, dev_virtual] + [Exception()] * 38

        dm_primary = MagicMock()
        dm_primary.PelsHeight = 1080
        dm_virtual = MagicMock()

        def mock_enum_settings(dev_name, mode):
            if dev_name == r"\\.\DISPLAY1":
                return dm_primary
            return dm_virtual

        mock_settings.side_effect = mock_enum_settings

        attach_virtual_display(width=1280, height=800, refresh_rate=165)

        self.assertEqual(dm_virtual.PelsWidth, 1280)
        self.assertEqual(dm_virtual.PelsHeight, 800)
        self.assertEqual(dm_virtual.Position_x, -1280)
        self.assertEqual(dm_virtual.Position_y, 280)
        self.assertEqual(dm_virtual.DisplayFrequency, 165)
        mock_change.assert_any_call(
            r"\\.\DISPLAY25", dm_virtual, win32con.CDS_UPDATEREGISTRY | win32con.CDS_NORESET
        )
        mock_change.assert_any_call(None, None, 0)


if __name__ == '__main__':
    unittest.main()
