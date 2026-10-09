import os
import unittest

class TestDriverInf(unittest.TestCase):
    def setUp(self):
        self.inf_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'server', 'driver', 'aoap_bin', 'opendisplay_aoap.inf'
        )

    def test_inf_exists_and_contains_hardware_ids(self):
        self.assertTrue(os.path.exists(self.inf_path), "INF file must exist")
        with open(self.inf_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        self.assertIn("VID_18D1&PID_2D00", content)
        self.assertIn("VID_18D1&PID_2D01", content)
        self.assertIn("WinUSB.sys", content)
        self.assertIn("{E1D13C8D-9B21-4E87-873B-15BC9C21A77E}", content)

if __name__ == '__main__':
    unittest.main()
