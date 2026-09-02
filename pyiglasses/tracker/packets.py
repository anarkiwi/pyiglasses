"""Tracker packet framing and decoding.

A binary packet is a 255 header, big endian 16 bit fields, and an arithmetic
checksum of everything before it.  In a continuous stream the header is not
unique, so the framer validates every candidate and steps one byte past a header
that fails, exactly as section B prescribes.  Candidates are checked all at once
against a cumulative sum rather than one packet at a time.
"""

from dataclasses import dataclass

import numpy as np

from .protocol import (
    DEGREES_PER_UNIT,
    FIXED_ONE,
    HEADER,
    PACKET_FIELDS,
    DataMode,
    packet_size,
)

#: A Microsoft mouse packet is three bytes; the tracker sets bit 7 on all of them
#: so that a 7 bit receiver reads it as a stop bit.
MOUSE_PACKET_SIZE = 3
MOUSE_SYNC = 0x40


def checksum(data):
    """The arithmetic checksum the tracker appends to a packet."""
    return int(np.sum(np.frombuffer(bytes(data), np.uint8), dtype=np.int64) & 0xFF)


def frame_packet(values, mode):
    """Build a binary packet, as the tracker would send it."""
    fields = np.asarray(values, np.int64)
    if fields.size != len(PACKET_FIELDS[DataMode(mode)]):
        raise ValueError(
            f"{DataMode(mode).name} packets carry {PACKET_FIELDS[DataMode(mode)]}"
        )
    body = np.empty(1 + fields.size * 2, np.uint8)
    body[0] = HEADER
    body[1:] = np.frombuffer(fields.astype(">i2").tobytes(), np.uint8)
    return bytes(body) + bytes([checksum(body)])


def find_packets(data, size):
    """Return the offsets of checksum valid, non overlapping packets."""
    data = (
        data if isinstance(data, np.ndarray) else np.frombuffer(bytes(data), np.uint8)
    )
    if data.size < size:
        return np.empty(0, np.int64)
    totals = np.concatenate(([0], np.cumsum(data, dtype=np.int64)))
    starts = np.flatnonzero(data[: data.size - size + 1] == HEADER)
    if not starts.size:
        return np.empty(0, np.int64)
    sums = totals[starts + size - 1] - totals[starts]
    valid = starts[(sums & 0xFF) == data[starts + size - 1]]
    accepted, end = [], 0
    for start in valid.tolist():
        if start >= end:
            accepted.append(start)
            end = start + size
    return np.asarray(accepted, np.int64)


def decode_fields(packets, mode):
    """Decode framed packets into their 16 bit fields.

    ``packets`` is an ``(n, size)`` array of whole packets.  Raw mode counts are
    unsigned 12 bit values; cooked and Euler fields are signed.
    """
    mode = DataMode(mode)
    size = packet_size(mode)
    packets = np.atleast_2d(np.asarray(packets, np.uint8))
    if packets.shape[1] != size:
        raise ValueError(
            f"{mode.name} packets are {size} bytes, got {packets.shape[1]}"
        )
    payload = np.ascontiguousarray(packets[:, 1 : size - 1])
    dtype = ">u2" if mode is DataMode.RAW else ">i2"
    return payload.view(dtype).astype(np.int32)


def tilt_compensated_yaw(magnetic, pitch, roll):
    """Yaw in degrees from a magnetic vector and the tilt the tracker reports.

    The tracker's axes are +X right, +Y up and +Z out of the face, and a reading
    is the world field seen in that frame, so the tilt is undone by rotating back
    about +Z by the roll and then about +X by the pitch.  What is left is a
    vector in the horizontal plane, and yaw is its bearing; positive yaw is a
    left head rotation, per section B.
    """
    magnetic = np.asarray(magnetic, np.float64)
    radians_pitch, radians_roll = np.radians(pitch), np.radians(roll)
    cos_r, sin_r = np.cos(radians_roll), np.sin(radians_roll)
    cos_p, sin_p = np.cos(radians_pitch), np.sin(radians_pitch)
    east, up, north = magnetic[..., 0], magnetic[..., 1], magnetic[..., 2]
    level_east = east * cos_r + up * sin_r
    level_up = -east * sin_r + up * cos_r
    level_north = north * cos_p - level_up * sin_p
    return np.degrees(np.arctan2(-level_east, level_north))


def magnetic_from_orientation(yaw, pitch, roll, dip=65.0):
    """The magnetic vector a tracker at this attitude would report.

    The exact inverse of :func:`tilt_compensated_yaw`, and the model that
    function assumes: the world field points north and down by ``dip`` degrees,
    and the body frame is reached by yawing, then pitching, then rolling.
    """
    yaw, pitch, roll = (
        np.radians(np.asarray(value, np.float64)) for value in (yaw, pitch, roll)
    )
    dip = np.radians(dip)
    east = -np.sin(yaw) * np.cos(dip)
    up = -np.sin(dip)
    north = np.cos(yaw) * np.cos(dip)
    # pitch about +X, then roll about +Z
    up, north = up * np.cos(pitch) - north * np.sin(pitch), up * np.sin(
        pitch
    ) + north * np.cos(pitch)
    east, up = east * np.cos(roll) - up * np.sin(roll), east * np.sin(
        roll
    ) + up * np.cos(roll)
    return np.stack(np.broadcast_arrays(east, up, north), axis=-1)


def format_ascii_packet(packet):
    """Render a binary packet as the space separated hex the ASCII modes use."""
    data = bytes(packet)
    fields = [f"{data[0]:02X}"]
    fields += [
        f"{int.from_bytes(data[i : i + 2], 'big'):04X}"
        for i in range(1, len(data) - 1, 2)
    ]
    fields.append(f"{data[-1]:02X}")
    return (" ".join(fields) + "\r\n").encode("ascii")


def parse_ascii_packet(line, size):
    """Parse a line of hex tokens back into a checksum valid binary packet.

    Tokens are accepted at any width, so a tracker that groups its hex by byte
    and one that groups by 16 bit field both decode.
    """
    text = (
        line.decode("ascii", "replace")
        if isinstance(line, (bytes, bytearray))
        else line
    )
    data = bytearray()
    for token in text.split():
        if len(token) % 2 or not all(
            char in "0123456789abcdefABCDEF" for char in token
        ):
            raise ValueError(f"{token!r} is not a whole number of hex bytes")
        data += bytes.fromhex(token)
    if len(data) != size:
        raise ValueError(f"ASCII packet holds {len(data)} bytes, want {size}")
    if data[0] != HEADER or checksum(data[:-1]) != data[-1]:
        raise ValueError("ASCII packet header or checksum is wrong")
    return bytes(data)


@dataclass(frozen=True)
class Sample:
    """One decoded orientation reading."""

    mode: DataMode
    fields: tuple
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    magnetic: tuple | None = None

    @property
    def angles(self):
        """(yaw, pitch, roll) in degrees, or None in raw mode."""
        if self.yaw is None:
            return None
        return (self.yaw, self.pitch, self.roll)


def decode_angles(fields, mode, yaw_sign=1):
    """Convert decoded packet fields into yaw, pitch and roll in degrees.

    Returns ``(angles, magnetic)``, both ``(n, 3)`` arrays; raw mode has no
    calibration behind it, so its angles are None.  ``yaw_sign`` corrects the
    firmware erratum below revision 001.003, which is a bug in the tracker's own
    Euler computation, so it applies to Euler mode only: cooked mode yaw is
    computed here, from a magnetic vector the erratum never touched.
    """
    mode = DataMode(mode)
    fields = np.atleast_2d(np.asarray(fields, np.float64))
    if mode is DataMode.EULER:
        angles = fields * DEGREES_PER_UNIT
        angles[:, 0] *= yaw_sign
        return angles, None
    magnetic = fields[:, :3] / FIXED_ONE
    if mode is DataMode.RAW:
        return None, magnetic
    pitch, roll = (fields[:, 3] * DEGREES_PER_UNIT, fields[:, 4] * DEGREES_PER_UNIT)
    yaw = tilt_compensated_yaw(magnetic, pitch, roll)
    return np.stack([yaw, pitch, roll], axis=1), magnetic


def decode_samples(packets, mode, yaw_sign=1):
    """Decode framed packets into :class:`Sample` objects."""
    mode = DataMode(mode)
    fields = decode_fields(packets, mode)
    angles, magnetic = decode_angles(fields, mode, yaw_sign)
    samples = []
    for index, row in enumerate(fields):
        angle = (None, None, None) if angles is None else tuple(angles[index])
        samples.append(
            Sample(
                mode=mode,
                fields=tuple(int(value) for value in row),
                yaw=angle[0],
                pitch=angle[1],
                roll=angle[2],
                magnetic=None if magnetic is None else tuple(magnetic[index]),
            )
        )
    return samples


class PacketReader:
    """Reassemble packets from a byte stream, resynchronising on bad checksums.

    Every start position in the buffer is decided once the bytes for a whole
    packet are present, so only the trailing partial packet is ever carried over
    and the buffer cannot grow without bound.
    """

    def __init__(self, mode):
        self.mode = DataMode(mode)
        self.size = packet_size(self.mode)
        self._tail = b""
        self.discarded = 0

    def feed(self, data):
        """Add received bytes and return whole packets as an (n, size) array."""
        buffer = np.frombuffer(self._tail + bytes(data), np.uint8)
        starts = find_packets(buffer, self.size)
        consumed = int(starts[-1]) + self.size if starts.size else 0
        keep_from = min(max(consumed, buffer.size - self.size + 1), buffer.size)
        self.discarded += keep_from - starts.size * self.size
        self._tail = buffer[keep_from:].tobytes()
        if not starts.size:
            return np.empty((0, self.size), np.uint8)
        return buffer[starts[:, None] + np.arange(self.size)[None, :]]

    def reset(self):
        """Drop anything held from a previous stream."""
        self._tail = b""


def _signed_byte(value):
    value &= 0xFF
    return value - 0x100 if value & 0x80 else value


def decode_mouse(packet):
    """Decode a three byte Microsoft mouse packet into (dx, dy, left, right)."""
    data = np.frombuffer(bytes(packet), np.uint8) & 0x7F
    if data.size != MOUSE_PACKET_SIZE:
        raise ValueError(
            f"mouse packets are {MOUSE_PACKET_SIZE} bytes, got {data.size}"
        )
    if not data[0] & MOUSE_SYNC:
        raise ValueError("mouse packet does not start with the sync bit set")
    high = int(data[0])
    delta_x = _signed_byte(((high & 0x03) << 6) | (int(data[1]) & 0x3F))
    delta_y = _signed_byte(((high & 0x0C) << 4) | (int(data[2]) & 0x3F))
    return delta_x, delta_y, bool(high & 0x20), bool(high & 0x10)


def frame_mouse(delta_x, delta_y, left=False, right=False):
    """Build a three byte mouse packet, as the tracker would send it."""
    delta_x, delta_y = (
        int(np.clip(value, -128, 127)) & 0xFF for value in (delta_x, delta_y)
    )
    high = MOUSE_SYNC | (0x20 if left else 0) | (0x10 if right else 0)
    high |= (delta_y >> 4) & 0x0C
    high |= (delta_x >> 6) & 0x03
    return bytes(value | 0x80 for value in (high, delta_x & 0x3F, delta_y & 0x3F))
