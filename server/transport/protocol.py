import struct

MSG_CONFIG = 1
MSG_VIDEO = 2
MSG_HEARTBEAT = 3

# Format: 4 bytes length (uint32 big-endian), 1 byte message type (uint8)
HEADER_FORMAT = '>IB'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def pack_message(msg_type: int, payload: bytes) -> bytes:
    total_len = len(payload) + 1  # 1 byte for type
    header = struct.pack(HEADER_FORMAT, total_len, msg_type)
    return header + payload


def unpack_header(data: bytes) -> tuple[int | None, int | None]:
    if len(data) < HEADER_SIZE:
        return None, None
    total_len, msg_type = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    payload_len = total_len - 1
    return msg_type, payload_len


def unpack_message(data: bytes) -> tuple[int | None, bytes | None]:
    msg_type, payload_len = unpack_header(data)
    if msg_type is None or payload_len is None:
        return None, None
    if len(data) < HEADER_SIZE + payload_len:
        return None, None
    payload = data[HEADER_SIZE : HEADER_SIZE + payload_len]
    return msg_type, payload
