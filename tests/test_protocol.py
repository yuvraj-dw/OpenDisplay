import unittest

from server.transport.protocol import (
    HEADER_SIZE,
    MSG_CONFIG,
    MSG_HEARTBEAT,
    MSG_VIDEO,
    pack_message,
    unpack_header,
    unpack_message,
)


class TestProtocol(unittest.TestCase):
    def test_pack_unpack_config(self):
        payload = b'{"width": 2560, "height": 1600, "fps": 60}'
        packed = pack_message(MSG_CONFIG, payload)
        self.assertEqual(len(packed), HEADER_SIZE + len(payload))

        msg_type, unpacked = unpack_message(packed)
        self.assertEqual(msg_type, MSG_CONFIG)
        self.assertEqual(unpacked, payload)

    def test_pack_unpack_video(self):
        nal_payload = b'\x00\x00\x00\x01\x67\x42\x00\x1f'
        packed = pack_message(MSG_VIDEO, nal_payload)
        self.assertEqual(len(packed), HEADER_SIZE + len(nal_payload))

        msg_type, unpacked = unpack_message(packed)
        self.assertEqual(msg_type, MSG_VIDEO)
        self.assertEqual(unpacked, nal_payload)

    def test_pack_unpack_heartbeat(self):
        payload = b''
        packed = pack_message(MSG_HEARTBEAT, payload)
        self.assertEqual(len(packed), HEADER_SIZE)

        msg_type, unpacked = unpack_message(packed)
        self.assertEqual(msg_type, MSG_HEARTBEAT)
        self.assertEqual(unpacked, payload)

    def test_unpack_header(self):
        payload = b'test payload'
        packed = pack_message(MSG_CONFIG, payload)
        msg_type, payload_len = unpack_header(packed)
        self.assertEqual(msg_type, MSG_CONFIG)
        self.assertEqual(payload_len, len(payload))

    def test_unpack_header_insufficient_data(self):
        short_data = b'\x00\x00'
        msg_type, payload_len = unpack_header(short_data)
        self.assertIsNone(msg_type)
        self.assertIsNone(payload_len)

        msg_type_msg, payload_unpacked = unpack_message(short_data)
        self.assertIsNone(msg_type_msg)
        self.assertIsNone(payload_unpacked)


if __name__ == '__main__':
    unittest.main()
