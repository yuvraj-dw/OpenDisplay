import unittest
from unittest.mock import MagicMock, patch
import win32con

from server import autostart
from opendisplay_server import SystemTray


class TestTrayAutostartToggle(unittest.TestCase):
    @patch('server.autostart.set_autostart')
    @patch('server.autostart.is_autostart_enabled')
    def test_toggle_logic_enable(self, mock_is_enabled, mock_set):
        mock_is_enabled.return_value = False
        new_state = not autostart.is_autostart_enabled()
        autostart.set_autostart(new_state)
        mock_set.assert_called_with(True)

    @patch('server.autostart.set_autostart')
    @patch('server.autostart.is_autostart_enabled')
    def test_toggle_logic_disable(self, mock_is_enabled, mock_set):
        mock_is_enabled.return_value = True
        new_state = not autostart.is_autostart_enabled()
        autostart.set_autostart(new_state)
        mock_set.assert_called_with(False)

    @patch('opendisplay_server.set_autostart')
    @patch('opendisplay_server.is_autostart_enabled')
    def test_system_tray_handle_menu_command_1005_enable(self, mock_is_enabled, mock_set):
        mock_is_enabled.return_value = False
        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray._handle_menu_command(1005)
        mock_is_enabled.assert_called_once()
        mock_set.assert_called_once_with(True)

    @patch('opendisplay_server.set_autostart')
    @patch('opendisplay_server.is_autostart_enabled')
    def test_system_tray_handle_menu_command_1005_disable(self, mock_is_enabled, mock_set):
        mock_is_enabled.return_value = True
        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray._handle_menu_command(1005)
        mock_is_enabled.assert_called_once()
        mock_set.assert_called_once_with(False)

    @patch('opendisplay_server.win32gui')
    @patch('opendisplay_server.is_autostart_enabled')
    def test_wnd_proc_menu_item_checked_when_enabled(self, mock_is_enabled, mock_win32gui):
        mock_is_enabled.return_value = True
        mock_win32gui.CreatePopupMenu.return_value = 12345
        mock_win32gui.GetCursorPos.return_value = (100, 200)
        mock_win32gui.TrackPopupMenu.return_value = 0

        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray.is_connected = False

        msg_tray = win32con.WM_USER + 20
        tray._wnd_proc(999, msg_tray, 0, win32con.WM_RBUTTONUP)

        # Check that win32gui.AppendMenu was called with MF_CHECKED for command 1005
        calls = mock_win32gui.AppendMenu.call_args_list
        found = False
        for call in calls:
            args, _ = call
            if len(args) >= 3 and args[2] == 1005:
                flags = args[1]
                self.assertTrue(flags & win32con.MF_CHECKED)
                self.assertEqual(args[3], "Start with Windows")
                found = True
                break
        self.assertTrue(found, "Menu item 1005 ('Start with Windows') was not appended")

    @patch('opendisplay_server.win32gui')
    @patch('opendisplay_server.is_autostart_enabled')
    def test_wnd_proc_menu_item_unchecked_when_disabled(self, mock_is_enabled, mock_win32gui):
        mock_is_enabled.return_value = False
        mock_win32gui.CreatePopupMenu.return_value = 12345
        mock_win32gui.GetCursorPos.return_value = (100, 200)
        mock_win32gui.TrackPopupMenu.return_value = 0

        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray.is_connected = False

        msg_tray = win32con.WM_USER + 20
        tray._wnd_proc(999, msg_tray, 0, win32con.WM_RBUTTONUP)

        calls = mock_win32gui.AppendMenu.call_args_list
        found = False
        for call in calls:
            args, _ = call
            if len(args) >= 3 and args[2] == 1005:
                flags = args[1]
                self.assertFalse(flags & win32con.MF_CHECKED)
                self.assertEqual(args[3], "Start with Windows")
                found = True
                break
        self.assertTrue(found, "Menu item 1005 ('Start with Windows') was not appended")

    @patch('opendisplay_server.set_autostart')
    @patch('opendisplay_server.is_autostart_enabled')
    @patch('opendisplay_server.win32gui')
    def test_wnd_proc_menu_command_1005_click(self, mock_win32gui, mock_is_enabled, mock_set):
        mock_is_enabled.return_value = False
        mock_win32gui.CreatePopupMenu.return_value = 12345
        mock_win32gui.GetCursorPos.return_value = (100, 200)
        mock_win32gui.TrackPopupMenu.return_value = 1005

        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray.is_connected = False

        msg_tray = win32con.WM_USER + 20
        tray._wnd_proc(999, msg_tray, 0, win32con.WM_RBUTTONUP)

        mock_set.assert_called_once_with(True)

    @patch('opendisplay_server.webbrowser.open')
    def test_handle_menu_command_1003(self, mock_webbrowser):
        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray._handle_menu_command(1003)
        mock_webbrowser.assert_called_once()

    def test_handle_menu_command_1004(self):
        tray = SystemTray.__new__(SystemTray)
        tray.server = MagicMock()
        tray._handle_menu_command(1004)
        tray.server.stop.assert_called_once()


if __name__ == '__main__':
    unittest.main()
