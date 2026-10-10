import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from server.autostart import (
    APP_VALUE_NAME,
    RUN_KEY_PATH,
    get_executable_command,
    is_autostart_enabled,
    set_autostart,
)


class TestAutostart(unittest.TestCase):
    @patch("winreg.OpenKey")
    @patch("winreg.QueryValueEx")
    def test_is_autostart_enabled_true(self, mock_query, mock_open):
        mock_query.return_value = (r'"C:\OpenDisplay\OpenDisplay.exe"', 1)
        self.assertTrue(is_autostart_enabled())
        mock_open.assert_called_once()
        mock_query.assert_called_once()

    @patch("winreg.OpenKey")
    def test_is_autostart_enabled_false_on_missing_key(self, mock_open):
        mock_open.side_effect = FileNotFoundError()
        self.assertFalse(is_autostart_enabled())

    @patch("winreg.OpenKey")
    @patch("winreg.QueryValueEx")
    def test_is_autostart_enabled_false_on_missing_value(self, mock_query, mock_open):
        mock_query.side_effect = FileNotFoundError()
        self.assertFalse(is_autostart_enabled())

    @patch("winreg.OpenKey")
    def test_is_autostart_enabled_false_on_general_exception(self, mock_open):
        mock_open.side_effect = PermissionError("Access denied")
        self.assertFalse(is_autostart_enabled())

    @patch("os.name", "posix")
    def test_is_autostart_enabled_non_windows(self):
        self.assertFalse(is_autostart_enabled())

    @patch("winreg.OpenKey")
    @patch("winreg.SetValueEx")
    def test_set_autostart_enable(self, mock_set, mock_open):
        mock_key = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_key
        res = set_autostart(True)
        self.assertTrue(res)
        mock_set.assert_called_once()
        args, kwargs = mock_set.call_args
        self.assertEqual(args[0], mock_key)
        self.assertEqual(args[1], APP_VALUE_NAME)

    @patch("winreg.OpenKey")
    @patch("winreg.DeleteValue")
    def test_set_autostart_disable(self, mock_del, mock_open):
        mock_key = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_key
        res = set_autostart(False)
        self.assertTrue(res)
        mock_del.assert_called_once_with(mock_key, APP_VALUE_NAME)

    @patch("winreg.OpenKey")
    @patch("winreg.DeleteValue")
    def test_set_autostart_disable_when_value_missing(self, mock_del, mock_open):
        mock_key = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_key
        mock_del.side_effect = FileNotFoundError()
        res = set_autostart(False)
        self.assertTrue(res)
        mock_del.assert_called_once_with(mock_key, APP_VALUE_NAME)

    @patch("winreg.OpenKey")
    def test_set_autostart_error_handling(self, mock_open):
        mock_open.side_effect = PermissionError("Access denied")
        res = set_autostart(True)
        self.assertFalse(res)

    @patch("os.name", "posix")
    def test_set_autostart_non_windows(self):
        self.assertFalse(set_autostart(True))
        self.assertFalse(set_autostart(False))

    @patch.object(sys, "frozen", True, create=True)
    @patch.object(sys, "executable", r"C:\Program Files\OpenDisplay\OpenDisplay.exe")
    def test_get_executable_command_frozen(self):
        cmd = get_executable_command()
        self.assertEqual(cmd, r'"C:\Program Files\OpenDisplay\OpenDisplay.exe"')

    def test_get_executable_command_dist_exe(self):
        # When not frozen and dist/OpenDisplay/OpenDisplay.exe exists
        with patch.object(sys, "frozen", False, create=True):
            with patch("os.path.exists") as mock_exists:
                def side_effect(path):
                    if path.endswith(os.path.join("dist", "OpenDisplay", "OpenDisplay.exe")):
                        return True
                    return False
                mock_exists.side_effect = side_effect
                cmd = get_executable_command()
                self.assertTrue(cmd.startswith('"'))
                self.assertTrue(cmd.endswith('OpenDisplay.exe"'))

    def test_get_executable_command_script_fallback(self):
        # When not frozen and dist/OpenDisplay/OpenDisplay.exe does not exist
        with patch.object(sys, "frozen", False, create=True):
            with patch("os.path.exists") as mock_exists:
                mock_exists.return_value = False
                with patch.object(sys, "executable", r"C:\Python310\python.exe"):
                    cmd = get_executable_command()
                    self.assertIn("python.exe", cmd)
                    self.assertIn("opendisplay_server.py", cmd)


if __name__ == "__main__":
    unittest.main()
