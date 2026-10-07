import unittest

import numpy as np

from server.capture.dxgi_capture import DxgiScreenCapture


class TestDxgiScreenCapture(unittest.TestCase):
    def test_enumeration_displays(self):
        capture = DxgiScreenCapture()
        displays = capture.list_displays()
        self.assertIsInstance(displays, list)
        self.assertGreater(len(displays), 0)
        disp = displays[0]
        self.assertIn('id', disp)
        self.assertIn('width', disp)
        self.assertIn('height', disp)
        self.assertGreater(disp['width'], 0)
        self.assertGreater(disp['height'], 0)

    def test_frame_acquisition(self):
        capture = DxgiScreenCapture()
        frame = capture.capture_frame(display_idx=0)
        self.assertIsNotNone(frame)
        self.assertIsInstance(frame, np.ndarray)
        self.assertEqual(len(frame.shape), 3)
        self.assertIn(frame.shape[2], (3, 4))
        self.assertEqual(frame.dtype, np.uint8)

    def test_mss_fallback(self):
        capture = DxgiScreenCapture(backend='mss')
        displays = capture.list_displays()
        self.assertGreater(len(displays), 0)
        frame = capture.capture_frame(0)
        self.assertIsNotNone(frame)
        self.assertIsInstance(frame, np.ndarray)

    def test_gdi_backend(self):
        try:
            capture = DxgiScreenCapture(backend='gdi')
            displays = capture.list_displays()
            self.assertGreater(len(displays), 0)
            frame = capture.capture_frame(0)
            self.assertIsNotNone(frame)
            self.assertIsInstance(frame, np.ndarray)
        except RuntimeError:
            pass  # If GDI is not supported in the running environment

    def test_headless_fallback(self):
        capture = DxgiScreenCapture(backend='headless')
        displays = capture.list_displays()
        self.assertGreaterEqual(len(displays), 1)
        frame = capture.capture_frame(0)
        self.assertIsNotNone(frame)
        self.assertEqual(frame.shape, (1080, 1920, 3))

    def test_invalid_display_index(self):
        capture = DxgiScreenCapture()
        with self.assertRaises(IndexError):
            capture.capture_frame(9999)

    def test_context_manager(self):
        with DxgiScreenCapture() as capture:
            displays = capture.list_displays()
            self.assertGreater(len(displays), 0)


if __name__ == '__main__':
    unittest.main()
