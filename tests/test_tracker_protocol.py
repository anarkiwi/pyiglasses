"""Command building and the version string."""

import pytest

from pyiglasses.tracker.protocol import (
    DataMode,
    SendFormat,
    SendMode,
    VersionInfo,
    format_version,
    mode_command,
    packet_size,
    parse_version,
    reset_command,
    stop_command,
    version_command,
)


def test_the_fixed_commands_match_the_specification():
    assert reset_command() == b"!R\r"
    assert version_command() == b"!V\r"
    assert stop_command() == b"!\r"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, b"!M1,P,B\r"),
        ({"magnetic_filter": 0, "tilt_filter": 0}, b"!M1,P,B,0,0\r"),
        ({"magnetic_filter": 7, "tilt_filter": 7}, b"!M1,P,B,7,7\r"),
    ],
)
def test_mode_commands_match_the_documented_examples(kwargs, expected):
    assert (
        mode_command(DataMode.COOKED, SendMode.POLLED, SendFormat.BINARY, **kwargs)
        == expected
    )


def test_a_mouse_mode_command_carries_all_seven_parameters():
    command = mode_command(3, "C", "B", 3, 3, 2, 2)
    assert command == b"!M3,C,B,3,3,2,2\r"


def test_modes_may_be_given_as_plain_values():
    assert mode_command(2, "P", "B", 3, 3) == b"!M2,P,B,3,3\r"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((1, "P", "B", 3, None), "together"),
        ((1, "P", "B", 8, 3), "outside 0-7"),
        ((3, "C", "B", None, None, 2, 2), "require the filter"),
        ((3, "C", "B", 3, 3, 2, None), "together"),
        ((3, "C", "B", 3, 3, 2, 11), "outside 0-9"),
    ],
)
def test_invalid_mode_commands_are_refused(args, message):
    with pytest.raises(ValueError, match=message):
        mode_command(*args)


def test_only_the_orientation_modes_have_packet_sizes():
    assert packet_size(DataMode.EULER) == 8
    assert packet_size(DataMode.COOKED) == packet_size(DataMode.RAW) == 12
    with pytest.raises(ValueError, match="does not send orientation"):
        packet_size(DataMode.MOUSE)


def test_version_strings_round_trip():
    info = VersionInfo("VIRTUAL I-O", "0001", "TRACKER", 1.001, 1.004, True)
    assert parse_version(format_version(info)) == info


@pytest.mark.parametrize(
    ("firmware", "inverted"),
    [(1.000, True), (1.002, True), (1.003, False), (1.004, False)],
)
def test_early_firmware_reports_yaw_with_the_wrong_sign(firmware, inverted):
    info = VersionInfo("VIRTUAL I-O", "0001", "TRACKER", 1.001, firmware, True)
    assert info.inverts_yaw is inverted
    assert info.yaw_sign == (-1 if inverted else 1)


def test_a_failed_self_test_is_reported():
    info = VersionInfo("VIRTUAL I-O", "0001", "TRACKER", 1.001, 1.004, False)
    assert format_version(info).endswith(b"E")
    assert not parse_version(format_version(info)).self_test_passed


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("M short", "characters"),
        ("X" + " " * 59, "expected 'M'"),
        (
            "M" + " " * 16 + "P" + " " * 16 + "T" + " " * 8 + "H001.000F001.000X",
            "self test",
        ),
        (
            "M" + " " * 16 + "P" + " " * 16 + "T" + " " * 8 + "Habcdefg" + "F001.000O",
            "not numbers",
        ),
    ],
)
def test_broken_version_strings_are_rejected(text, message):
    with pytest.raises(ValueError, match=message):
        parse_version(text)
