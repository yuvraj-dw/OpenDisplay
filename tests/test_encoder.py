import unittest

import numpy as np

from server.encoder.hw_encoder import HardwareEncoder, HwEncoder


class TestHardwareEncoder(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.frame[100:200, 100:200, :] = 255

    def test_encode_image_jpeg(self):
        encoder = HardwareEncoder(codec='jpeg')
        encoded = encoder.encode(self.frame)
        self.assertIsInstance(encoded, bytes)
        self.assertGreater(len(encoded), 0)
        # JPEG SOI marker check
        self.assertEqual(encoded[:2], b'\xff\xd8')

    def test_encode_video_frame_h264(self):
        encoder = HardwareEncoder(codec='auto', width=640, height=480, fps=60)
        encoded = encoder.encode(self.frame)
        self.assertIsInstance(encoded, bytes)
        self.assertGreater(len(encoded), 0)
        encoder.close()

    def test_alias_hw_encoder(self):
        self.assertIs(HardwareEncoder, HwEncoder)

    def test_low_latency_encoding(self):
        with HardwareEncoder(codec='jpeg') as encoder:
            data1 = encoder.encode(self.frame)
            data2 = encoder.encode(self.frame)
            self.assertGreater(len(data1), 0)
            self.assertGreater(len(data2), 0)


if __name__ == '__main__':
    unittest.main()
