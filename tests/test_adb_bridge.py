import unittest
from unittest.mock import MagicMock, patch

from server.transport.adb_bridge import AdbBridge


class TestAdbBridge(unittest.TestCase):
    @patch('shutil.which', return_value='/usr/bin/adb')
    def test_custom_or_detected_adb(self, mock_which):
        bridge = AdbBridge('custom_adb')
        self.assertEqual(bridge.adb, 'custom_adb')

        bridge_default = AdbBridge()
        self.assertEqual(bridge_default.adb, '/usr/bin/adb')

    @patch('subprocess.run')
    def test_is_device_connected_true(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="List of devices attached\nemulator-5554\tdevice\n\n",
            returncode=0
        )
        bridge = AdbBridge('adb')
        self.assertTrue(bridge.is_device_connected())
        mock_run.assert_called_once_with(['adb', 'devices'], capture_output=True, text=True)

    @patch('subprocess.run')
    def test_is_device_connected_false_when_unauthorized(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="List of devices attached\nemulator-5554\tunauthorized\n\n",
            returncode=0
        )
        bridge = AdbBridge('adb')
        self.assertFalse(bridge.is_device_connected())

    @patch('subprocess.run')
    def test_is_device_connected_false_when_empty(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="List of devices attached\n\n",
            returncode=0
        )
        bridge = AdbBridge('adb')
        self.assertFalse(bridge.is_device_connected())

    @patch('subprocess.run')
    def test_forward_port_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        bridge = AdbBridge('adb')
        self.assertTrue(bridge.forward_port(7070, 7070))
        mock_run.assert_called_once_with(
            ['adb', 'forward', 'tcp:7070', 'tcp:7070'],
            capture_output=True,
            text=True
        )

    @patch('subprocess.run')
    def test_forward_port_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        bridge = AdbBridge('adb')
        self.assertFalse(bridge.forward_port(7070, 7070))


if __name__ == '__main__':
    unittest.main()
