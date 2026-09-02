"""The i-glasses! Tracker serial protocol.

Commands are printable ASCII.  Every command except ``S`` starts with ``!`` and
ends with a carriage return, and the tracker answers ``O`` for ok or ``E`` for an
error.  ``S`` asks for one packet, or starts the stream in a continuous mode;
``!`` stops a stream.  Developer Kit v1.2 section B.
"""

from dataclasses import dataclass
from enum import Enum, IntEnum

# The tracker auto detects the host rate, so a driver scans until one answers.
# Fastest first: section D puts the response time under 15 ms at the top rates.
BAUD_RATES = (19200, 9600, 4800, 2400, 1200)
MOUSE_BAUD_RATE = 1200

HEADER = 0xFF
ATTENTION = b"!"
TERMINATOR = b"\r"
SEND = b"S"
OK = b"O"
ERROR = b"E"

# Angles are signed 16 bit fixed point where a full 180 degrees is 1 << 14.
FIXED_ONE = 1 << 14
DEGREES_PER_UNIT = 180.0 / FIXED_ONE

FILTER_RANGE = range(0, 8)
MOUSE_RANGE = range(0, 10)

# Firmware before this revision reports the wrong sign for yaw in Euler mode.
YAW_SIGN_FIXED_IN = 1.003


class DataMode(IntEnum):
    """What the tracker sends."""

    RAW = 0
    COOKED = 1
    EULER = 2
    MOUSE = 3
    CYBERMAXX = 4


class SendMode(Enum):
    """When the tracker sends it."""

    POLLED = "P"
    CONTINUOUS = "C"
    MOUSE_DELTA = "0"
    MOUSE_REFERENCE = "1"


class SendFormat(Enum):
    """How the tracker encodes it."""

    ASCII = "A"
    BINARY = "B"


#: Binary packet length per data mode, including header and checksum.
PACKET_SIZES = {DataMode.RAW: 12, DataMode.COOKED: 12, DataMode.EULER: 8}

#: Field names carried by each data mode's packet, in order.
PACKET_FIELDS = {
    DataMode.RAW: ("x", "y", "z", "pitch", "roll"),
    DataMode.COOKED: ("x", "y", "z", "pitch", "roll"),
    DataMode.EULER: ("yaw", "pitch", "roll"),
}


def packet_size(mode):
    """Return the binary packet length for a data mode."""
    try:
        return PACKET_SIZES[DataMode(mode)]
    except (KeyError, ValueError):
        raise ValueError(
            f"data mode {mode!r} does not send orientation packets"
        ) from None


def stop_command():
    """Stop a continuous stream and return the tracker to accepting commands."""
    return ATTENTION + TERMINATOR


def reset_command():
    """Reset to the default state: cooked, polled, binary."""
    return ATTENTION + b"R" + TERMINATOR


def version_command():
    """Ask for the revision string and self test result."""
    return ATTENTION + b"V" + TERMINATOR


def mode_command(
    data_mode,
    send_mode,
    send_format,
    magnetic_filter=None,
    tilt_filter=None,
    sensitivity=None,
    threshold=None,
):
    """Build a ``!M`` mode command.

    Filter strengths run 0 (none) to 7 (maximum) and are optional, but the mouse
    sensitivity and threshold may only be given when the filters are too.
    """
    data_mode = DataMode(data_mode)
    send_mode = SendMode(send_mode)
    send_format = SendFormat(send_format)
    parts = [str(int(data_mode)), send_mode.value, send_format.value]

    filters = (magnetic_filter, tilt_filter)
    mouse = (sensitivity, threshold)
    if any(value is not None for value in filters):
        if any(value is None for value in filters):
            raise ValueError("magnetic and tilt filters must be given together")
        for value in filters:
            if value not in FILTER_RANGE:
                raise ValueError(f"filter {value} outside 0-7")
        parts += [str(int(value)) for value in filters]
    if any(value is not None for value in mouse):
        if any(value is None for value in mouse):
            raise ValueError("mouse sensitivity and threshold must be given together")
        if len(parts) == 3:
            raise ValueError("mouse settings require the filter settings as well")
        for value in mouse:
            if value not in MOUSE_RANGE:
                raise ValueError(f"mouse setting {value} outside 0-9")
        parts += [str(int(value)) for value in mouse]
    return ATTENTION + b"M" + ",".join(parts).encode("ascii") + TERMINATOR


@dataclass(frozen=True)
class VersionInfo:
    """The tracker's identity, as reported by ``!V``."""

    manufacturer: str
    product: str
    product_type: str
    hardware: float
    firmware: float
    self_test_passed: bool

    @property
    def inverts_yaw(self):
        """True when this firmware has the Euler mode yaw sign bug."""
        return self.firmware < YAW_SIGN_FIXED_IN

    @property
    def yaw_sign(self):
        """The correction to apply to Euler mode yaw."""
        return -1 if self.inverts_yaw else 1


# M<16 chars>P<16 chars>T<8 chars>Hxxx.xxxFxxx.xxx, then O or E for the self test.
_VERSION_LAYOUT = (("M", 16), ("P", 16), ("T", 8), ("H", 7), ("F", 7))
VERSION_LENGTH = sum(1 + width for _, width in _VERSION_LAYOUT) + 1


def parse_version(data):
    """Parse a ``!V`` response into a :class:`VersionInfo`."""
    text = (
        data.decode("ascii", "replace")
        if isinstance(data, (bytes, bytearray))
        else data
    )
    if len(text) < VERSION_LENGTH:
        raise ValueError(
            f"version string is {len(text)} characters, want {VERSION_LENGTH}"
        )
    fields, offset = [], 0
    for marker, width in _VERSION_LAYOUT:
        if text[offset] != marker:
            raise ValueError(
                f"expected {marker!r} at offset {offset} of the version string"
            )
        fields.append(text[offset + 1 : offset + 1 + width].strip())
        offset += 1 + width
    result = text[offset]
    if result not in "OE":
        raise ValueError(
            f"version string ends with {result!r}, want the self test result"
        )
    try:
        hardware, firmware = float(fields[3]), float(fields[4])
    except ValueError:
        raise ValueError("hardware and firmware revisions are not numbers") from None
    return VersionInfo(
        fields[0], fields[1], fields[2], hardware, firmware, result == "O"
    )


def format_version(info):
    """Render a :class:`VersionInfo` back into a ``!V`` response."""
    return (
        f"M{info.manufacturer:<16.16}P{info.product:<16.16}T{info.product_type:<8.8}"
        f"H{info.hardware:07.3f}F{info.firmware:07.3f}{'O' if info.self_test_passed else 'E'}"
    ).encode("ascii")
