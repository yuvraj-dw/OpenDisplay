import unittest

import numpy as np

from server.encoder.hw_encoder import HardwareEncoder, HwEncoder, extract_nal_units


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

    def test_extract_nal_units(self):
        self.assertEqual(extract_nal_units(b''), [])
        self.assertEqual(extract_nal_units(b'no_start_code'), [b'no_start_code'])

        raw = b'\x00\x00\x00\x01\x67SPS\x00\x00\x00\x01\x68PPS\x00\x00\x01\x65IDR'
        nals = extract_nal_units(raw)
        self.assertEqual(len(nals), 3)
        self.assertEqual(nals[0], b'\x00\x00\x00\x01\x67SPS')
        self.assertEqual(nals[1], b'\x00\x00\x00\x01\x68PPS')
        self.assertEqual(nals[2], b'\x00\x00\x01\x65IDR')

    def test_encode_frame_nal_units(self):
        with HardwareEncoder(codec='dummy') as encoder:
            chunks = encoder.encode_frame(self.frame)
            self.assertEqual(chunks, [b'dummy_encoded_frame_data'])

        with HardwareEncoder(codec='jpeg') as encoder:
            chunks = encoder.encode_frame(self.frame)
            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0][:2], b'\xff\xd8')

        with HardwareEncoder(codec='auto', width=640, height=480, fps=60) as encoder:
            chunks = encoder.encode_frame(self.frame)
            self.assertIsInstance(chunks, list)
            self.assertGreater(len(chunks), 0)
            for chunk in chunks:
                self.assertTrue(chunk.startswith(b'\x00\x00\x00\x01') or chunk.startswith(b'\x00\x00\x01') or chunk.startswith(b'\xff\xd8'))


if __name__ == '__main__':
    unittest.main()
