import os
import subprocess
import unittest
from unittest.mock import MagicMock, call, patch

from opendisplay_server import OpenDisplayServer


class TestHostWake(unittest.TestCase):
    @patch('subprocess.run')
    @patch('os.path.exists', return_value=True)
    def test_launch_tablet_viewer_sends_wakeup_keyevent(self, mock_exists, mock_run):
        server = OpenDisplayServer(port=0)
        mock_run.reset_mock()
        server.adb = "adb.exe"
        server.launch_tablet_viewer()

        # Verify keyevent 224 was sent
        wakeup_call = False
        dismiss_call = False
        am_start_call = False
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            if cmd == ["adb.exe", "shell", "input", "keyevent", "224"]:
                wakeup_call = True
                self.assertEqual(call_args[1].get('creationflags'), 0x08000000)
                self.assertEqual(call_args[1].get('capture_output'), True)
                self.assertEqual(call_args[1].get('timeout'), 2)
            elif cmd == ["adb.exe", "shell", "wm", "dismiss-keyguard"]:
                dismiss_call = True
                self.assertEqual(call_args[1].get('creationflags'), 0x08000000)
                self.assertEqual(call_args[1].get('capture_output'), True)
                self.assertEqual(call_args[1].get('timeout'), 2)
            elif "am" in cmd and "start" in cmd:
                am_start_call = True
                self.assertEqual(call_args[1].get('creationflags'), 0x08000000)
                self.assertEqual(call_args[1].get('capture_output'), True)
                self.assertEqual(call_args[1].get('timeout'), 3)

        self.assertTrue(wakeup_call, "Must send KEYCODE_WAKEUP (224)")
        self.assertTrue(dismiss_call, "Must send wm dismiss-keyguard")
        self.assertTrue(am_start_call, "Must send am start")

    @patch('subprocess.run')
    @patch('os.path.exists', return_value=True)
    def test_launch_tablet_viewer_call_order(self, mock_exists, mock_run):
        server = OpenDisplayServer(port=0)
        mock_run.reset_mock()
        server.adb = "adb.exe"
        server.launch_tablet_viewer()

        expected_calls = [
            call(["adb.exe", "shell", "input", "keyevent", "224"], capture_output=True, timeout=2, creationflags=0x08000000),
            call(["adb.exe", "shell", "wm", "dismiss-keyguard"], capture_output=True, timeout=2, creationflags=0x08000000),
            call(["adb.exe", "shell", "am", "start", "-n", "com.display.usbclient/.MainActivity"], capture_output=True, timeout=3, creationflags=0x08000000),
        ]
        mock_run.assert_has_calls(expected_calls, any_order=False)

    @patch('subprocess.run')
    @patch('os.path.exists', return_value=False)
    def test_launch_tablet_viewer_adb_not_found(self, mock_exists, mock_run):
        server = OpenDisplayServer.__new__(OpenDisplayServer)
        server.adb = "nonexistent_adb.exe"
        server.launch_tablet_viewer()
        mock_run.assert_not_called()

    @patch('subprocess.run')
    def test_launch_tablet_viewer_adb_is_none(self, mock_run):
        server = OpenDisplayServer.__new__(OpenDisplayServer)
        server.adb = None
        server.launch_tablet_viewer()
        mock_run.assert_not_called()

    @patch('opendisplay_server.logger.warning')
    @patch('subprocess.run', side_effect=Exception("adb timeout"))
    @patch('os.path.exists', return_value=True)
    def test_launch_tablet_viewer_handles_exception(self, mock_exists, mock_run, mock_logger_warning):
        server = OpenDisplayServer.__new__(OpenDisplayServer)
        server.adb = "adb.exe"
        # Should catch exception and log warning without raising
        server.launch_tablet_viewer()
        mock_logger_warning.assert_called_once()
        self.assertIn("Failed waking tablet viewer", mock_logger_warning.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
