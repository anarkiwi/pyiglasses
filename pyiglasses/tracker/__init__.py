"""Driver for the Virtual i-O i-glasses! head tracker."""

from .device import MouseSample, SerialTransport, Tracker, TrackerError, TrackerTimeout
from .packets import (
    PacketReader,
    Sample,
    decode_fields,
    decode_samples,
    find_packets,
    magnetic_from_orientation,
    tilt_compensated_yaw,
)
from .protocol import (
    BAUD_RATES,
    DataMode,
    SendFormat,
    SendMode,
    VersionInfo,
    mode_command,
    parse_version,
)
from .simulator import SimulatedTracker

__all__ = [
    "BAUD_RATES",
    "DataMode",
    "MouseSample",
    "PacketReader",
    "Sample",
    "SendFormat",
    "SendMode",
    "SerialTransport",
    "SimulatedTracker",
    "Tracker",
    "TrackerError",
    "TrackerTimeout",
    "VersionInfo",
    "decode_fields",
    "decode_samples",
    "find_packets",
    "magnetic_from_orientation",
    "mode_command",
    "parse_version",
    "tilt_compensated_yaw",
]
