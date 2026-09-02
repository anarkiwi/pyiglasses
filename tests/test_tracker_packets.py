"""Packet framing, decoding, and the tilt compensated compass."""

import numpy as np
import pytest

from pyiglasses.tracker.packets import (
    PacketReader,
    checksum,
    decode_angles,
    decode_fields,
    decode_mouse,
    decode_samples,
    find_packets,
    format_ascii_packet,
    frame_mouse,
    frame_packet,
    magnetic_from_orientation,
    parse_ascii_packet,
    tilt_compensated_yaw,
)
from pyiglasses.tracker.protocol import DEGREES_PER_UNIT, FIXED_ONE, DataMode

EULER = [1000, -2000, 3000]
COOKED = [4000, -5000, 6000, 1000, -1000]


def rotation_x(angle):
    cos, sin = np.cos(angle), np.sin(angle)
    return np.array([[1, 0, 0], [0, cos, -sin], [0, sin, cos]])


def rotation_y(angle):
    cos, sin = np.cos(angle), np.sin(angle)
    return np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]])


def rotation_z(angle):
    cos, sin = np.cos(angle), np.sin(angle)
    return np.array([[cos, -sin, 0], [sin, cos, 0], [0, 0, 1]])


def body_field(yaw, pitch, roll, dip):
    """The world field seen from the head, built from first principles."""
    world = np.array([0.0, -np.sin(np.radians(dip)), np.cos(np.radians(dip))])
    return (
        rotation_z(np.radians(roll))
        @ rotation_x(np.radians(pitch))
        @ rotation_y(np.radians(-yaw))
        @ world
    )


@pytest.mark.parametrize(
    ("values", "mode"), [(EULER, DataMode.EULER), (COOKED, DataMode.COOKED)]
)
def test_packets_round_trip(values, mode):
    packet = frame_packet(values, mode)
    assert packet[0] == 0xFF
    assert checksum(packet[:-1]) == packet[-1]
    assert list(decode_fields([list(packet)], mode)[0]) == values


def test_raw_fields_are_unsigned():
    packet = frame_packet([4095, 0, 2048, 4095, 0], DataMode.RAW)
    assert list(decode_fields([list(packet)], DataMode.RAW)[0]) == [
        4095,
        0,
        2048,
        4095,
        0,
    ]


def test_packets_with_the_wrong_field_count_are_refused():
    with pytest.raises(ValueError, match="packets carry"):
        frame_packet([1, 2], DataMode.EULER)


def test_decoding_the_wrong_packet_length_is_refused():
    with pytest.raises(ValueError, match="are 8 bytes"):
        decode_fields(np.zeros((1, 12), np.uint8), DataMode.EULER)


def test_framing_skips_garbage_and_false_headers():
    packet = frame_packet(EULER, DataMode.EULER)
    stream = (
        b"\x00\xff\x01\x02"
        + packet
        + b"\xff\xff"
        + frame_packet([0, 0, 0], DataMode.EULER)
    )
    reader = PacketReader(DataMode.EULER)
    packets = reader.feed(stream)
    assert packets.shape == (2, 8)
    assert reader.discarded == 6
    assert list(decode_fields(packets, DataMode.EULER)[0]) == EULER


def test_a_corrupted_packet_is_dropped_and_the_next_one_is_found():
    good = frame_packet(EULER, DataMode.EULER)
    broken = bytearray(good)
    broken[-1] ^= 0xFF
    packets = PacketReader(DataMode.EULER).feed(bytes(broken) + good)
    assert packets.shape[0] == 1
    assert list(decode_fields(packets, DataMode.EULER)[0]) == EULER


def test_packets_split_across_reads_are_reassembled():
    stream = b"".join(frame_packet(EULER, DataMode.EULER) for _ in range(4))
    reader = PacketReader(DataMode.EULER)
    found = sum(
        reader.feed(stream[at : at + 3]).shape[0] for at in range(0, len(stream), 3)
    )
    assert found == 4
    assert reader.discarded == 0


def test_the_reader_never_grows_without_bound():
    reader = PacketReader(DataMode.COOKED)
    for _ in range(20):
        assert reader.feed(b"\xff" * 50).shape[0] == 0
    assert len(reader._tail) < reader.size  # pylint: disable=protected-access


def test_reset_drops_a_partial_packet():
    packet = frame_packet(EULER, DataMode.EULER)
    reader = PacketReader(DataMode.EULER)
    reader.feed(packet[:5])
    reader.reset()
    assert reader.feed(packet[5:]).shape[0] == 0


def test_find_packets_on_a_short_buffer_finds_nothing():
    assert find_packets(b"\xff\x00", 8).size == 0
    assert find_packets(b"\x00" * 32, 8).size == 0


def test_euler_fields_convert_to_degrees():
    angles, magnetic = decode_angles([EULER], DataMode.EULER)
    assert magnetic is None
    assert angles[0][0] == pytest.approx(1000 * DEGREES_PER_UNIT)


def test_the_yaw_sign_correction_is_applied():
    angles, _ = decode_angles([EULER], DataMode.EULER, yaw_sign=-1)
    assert angles[0][0] == pytest.approx(-1000 * DEGREES_PER_UNIT)


def test_raw_mode_has_no_angles():
    angles, magnetic = decode_angles([COOKED], DataMode.RAW)
    assert angles is None
    assert magnetic[0][0] == pytest.approx(4000 / FIXED_ONE)


def test_samples_carry_their_fields_and_angles():
    packet = frame_packet(EULER, DataMode.EULER)
    sample = decode_samples([list(packet)], DataMode.EULER)[0]
    assert sample.fields == tuple(EULER)
    assert sample.angles == (sample.yaw, sample.pitch, sample.roll)
    raw = decode_samples([list(frame_packet(COOKED, DataMode.RAW))], DataMode.RAW)[0]
    assert raw.angles is None


@pytest.mark.parametrize("dip", [0.0, 65.0, -30.0])
def test_yaw_is_recovered_from_a_tilted_magnetic_reading(dip):
    """Against rotation matrices written out independently of the driver."""
    rng = np.random.default_rng(7)
    for _ in range(200):
        yaw = rng.uniform(-179.0, 179.0)
        pitch, roll = rng.uniform(-80.0, 80.0, 2)
        measured = body_field(yaw, pitch, roll, dip)
        assert float(tilt_compensated_yaw(measured, pitch, roll)) == pytest.approx(
            yaw, abs=1e-9
        )


def test_the_forward_model_is_the_exact_inverse():
    yaw, pitch, roll = 33.0, -12.0, 44.0
    assert magnetic_from_orientation(yaw, pitch, roll, dip=65.0) == pytest.approx(
        body_field(yaw, pitch, roll, 65.0), abs=1e-12
    )


def test_cooked_mode_yaw_comes_from_the_magnetometer():
    yaw, pitch, roll = -70.0, 15.0, -5.0
    magnetic = magnetic_from_orientation(yaw, pitch, roll) * FIXED_ONE
    fields = list(magnetic) + [pitch / DEGREES_PER_UNIT, roll / DEGREES_PER_UNIT]
    angles, _ = decode_angles([fields], DataMode.COOKED)
    assert angles[0] == pytest.approx([yaw, pitch, roll], abs=1e-6)


def test_yaw_is_computed_for_a_whole_capture_at_once():
    yaw = np.linspace(-170.0, 170.0, 64)
    pitch = np.zeros(64)
    magnetic = magnetic_from_orientation(yaw, pitch, pitch)
    assert tilt_compensated_yaw(magnetic, pitch, pitch) == pytest.approx(yaw, abs=1e-9)


def test_ascii_packets_round_trip_at_either_grouping():
    packet = frame_packet(EULER, DataMode.EULER)
    assert parse_ascii_packet(format_ascii_packet(packet), 8) == packet
    by_byte = " ".join(f"{byte:02X}" for byte in packet)
    assert parse_ascii_packet(by_byte, 8) == packet


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("FF 03E", "hex bytes"),
        ("FF zz", "hex bytes"),
        ("FF 0000", "holds"),
        ("00 0000 0000 0000 00", "header or checksum"),
    ],
)
def test_broken_ascii_packets_are_rejected(line, message):
    with pytest.raises(ValueError, match=message):
        parse_ascii_packet(line, 8)


@pytest.mark.parametrize(
    ("delta_x", "delta_y", "left", "right"),
    [
        (0, 0, False, False),
        (-5, 7, True, False),
        (127, -128, False, True),
        (-1, -1, True, True),
    ],
)
def test_mouse_packets_round_trip(delta_x, delta_y, left, right):
    packet = frame_mouse(delta_x, delta_y, left, right)
    assert all(byte & 0x80 for byte in packet), "bit 7 stands in for the stop bit"
    assert decode_mouse(packet) == (delta_x, delta_y, left, right)


def test_mouse_deltas_are_clamped_to_a_byte():
    assert decode_mouse(frame_mouse(1000, -1000))[:2] == (127, -128)


@pytest.mark.parametrize(
    ("packet", "message"),
    [(b"\x80\x80", "3 bytes"), (b"\x80\x80\x80", "sync bit")],
)
def test_broken_mouse_packets_are_rejected(packet, message):
    with pytest.raises(ValueError, match=message):
        decode_mouse(packet)


def test_the_yaw_erratum_correction_does_not_touch_cooked_mode():
    """The erratum is in the tracker's Euler maths; cooked yaw is computed here."""
    fields = list(magnetic_from_orientation(30.0, 0.0, 0.0) * FIXED_ONE) + [0, 0]
    plain, _ = decode_angles([fields], DataMode.COOKED)
    corrected, _ = decode_angles([fields], DataMode.COOKED, yaw_sign=-1)
    assert corrected[0][0] == pytest.approx(plain[0][0]) == pytest.approx(30.0)
