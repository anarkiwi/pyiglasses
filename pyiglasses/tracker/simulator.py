"""A software tracker that speaks the real protocol.

The hardware is thirty years old and scarce, so the driver is developed and
tested against this instead: it accepts the same commands, answers with the same
result codes, frames the same packets, and can be told to have the firmware
revision whose Euler yaw sign is inverted or to sit at an unexpected line rate.

Raw mode counts are a plausible stand in, not a model of the real sensors; the
developer kit describes raw mode as factory debugging only.
"""

import numpy as np

from .packets import (
    format_ascii_packet,
    frame_mouse,
    frame_packet,
    magnetic_from_orientation,
)
from .protocol import (
    DEGREES_PER_UNIT,
    ERROR,
    FILTER_RANGE,
    FIXED_ONE,
    MOUSE_RANGE,
    OK,
    DataMode,
    SendFormat,
    SendMode,
    VersionInfo,
    format_version,
)

#: The attributes ``!R`` restores from their class defaults.
RESET_STATE = (
    "data_mode",
    "send_mode",
    "send_format",
    "magnetic_filter",
    "tilt_filter",
    "sensitivity",
    "threshold",
    "streaming",
)

RAW_CENTRE = 2048
RAW_FULL_SCALE = 4095
INT16 = (-32768, 32767)

#: One X mickey per this many degrees of yaw at sensitivity 1, and one Y mickey
#: per this many degrees of pitch (section B-8).
MICKEY_YAW_DEGREES = 0.25
MICKEY_PITCH_DEGREES = 1.0


def sweep(index):
    """A slow, repeatable head movement: yaw, pitch and roll in degrees."""
    phase = index / 30.0
    return (
        60.0 * np.sin(phase),
        20.0 * np.sin(0.7 * phase),
        10.0 * np.sin(0.3 * phase),
    )


class SimulatedTracker:
    """A transport that behaves like an i-glasses! Tracker.

    The class attributes below are the state ``!R`` returns the tracker to:
    cooked, polled, binary, per section B.
    """

    data_mode = DataMode.COOKED
    send_mode = SendMode.POLLED
    send_format = SendFormat.BINARY
    magnetic_filter = 0
    tilt_filter = 0
    sensitivity = 1
    threshold = 0
    streaming = False

    def __init__(
        self,
        orientation=sweep,
        firmware=1.004,
        hardware=1.001,
        baudrate=9600,
        device_baudrate=9600,
        self_test=True,
        dip=65.0,
        manufacturer="VIRTUAL I-O",
        product="I-GLASSES",
        product_type="TRACKER",
    ):
        self.orientation = orientation
        self.baudrate = baudrate
        self.device_baudrate = device_baudrate
        self.dip = dip
        self.version_info = VersionInfo(
            manufacturer, product, product_type, hardware, firmware, self_test
        )
        self.index = 0
        self.commands = []
        self._output = bytearray()
        self._command = None
        self._mouse_residual = np.zeros(2)
        self._last_angles = None
        self.reset_state()

    # -- transport interface -------------------------------------------------

    def read(self, size):
        """Return up to ``size`` bytes, generating more if a stream is running."""
        if self.baudrate != self.device_baudrate:
            return b""
        if not self._output and self.streaming:
            self._emit()
        data, self._output = bytes(self._output[:size]), self._output[size:]
        return data

    def write(self, data):
        """Feed command bytes to the tracker."""
        if self.baudrate != self.device_baudrate:
            return len(data)
        for byte in bytes(data):
            self._consume(byte)
        return len(data)

    def inject(self, data):
        """Put bytes in front of the next read, as line noise would."""
        self._output[:0] = bytes(data)

    def reset_input_buffer(self):
        """Throw away anything waiting to be read."""
        self._output.clear()

    def close(self):
        """Stop the stream."""
        self.streaming = False

    # -- tracker state -------------------------------------------------------

    def reset_state(self):
        """Return to the documented reset state, as the ``!R`` command does."""
        for name in RESET_STATE:
            setattr(self, name, getattr(type(self), name))
        self._mouse_residual[:] = 0.0
        self._last_angles = None

    def _consume(self, byte):
        if self._command is not None:
            if byte == ord("\r"):
                self._dispatch(bytes(self._command))
                self._command = None
            else:
                self._command.append(byte)
            return
        if byte == ord("!"):
            self.streaming = False
            self._command = bytearray()
        elif byte == ord("S"):
            if self.send_mode is SendMode.POLLED:
                self._emit()
            else:
                self.streaming = True
                self._emit()

    def _dispatch(self, command):
        self.commands.append(command)
        if command == b"":
            self._output += OK
        elif command == b"R":
            self.reset_state()
            self._output += OK
        elif command == b"V":
            self._output += format_version(self.version_info)
        elif command[:1] == b"M":
            self._output += OK if self._set_mode(command[1:]) else ERROR
        else:
            self._output += ERROR

    def _set_mode(self, arguments):
        parts = arguments.decode("ascii", "replace").split(",")
        if len(parts) not in (3, 5, 7):
            return False
        try:
            data_mode = DataMode(int(parts[0]))
            send_mode = SendMode(parts[1])
            send_format = SendFormat(parts[2])
            filters = [int(value) for value in parts[3:5]]
            mouse = [int(value) for value in parts[5:7]]
        except ValueError:
            return False
        if any(value not in FILTER_RANGE for value in filters):
            return False
        if any(value not in MOUSE_RANGE for value in mouse):
            return False
        if data_mode is DataMode.CYBERMAXX:
            return False
        self.data_mode, self.send_mode, self.send_format = (
            data_mode,
            send_mode,
            send_format,
        )
        if filters:
            self.magnetic_filter, self.tilt_filter = filters
        if mouse:
            self.sensitivity, self.threshold = mouse
        self.streaming = False
        self._last_angles = None
        return True

    # -- packet generation ---------------------------------------------------

    def _emit(self):
        angles = tuple(float(value) for value in self.orientation(self.index))
        self.index += 1
        if self.data_mode in (DataMode.MOUSE, DataMode.CYBERMAXX):
            packet = self._mouse_packet(angles)
        else:
            packet = frame_packet(self._fields(angles), self.data_mode)
        if packet is None:
            return
        self._output += (
            format_ascii_packet(packet)
            if self.send_format is SendFormat.ASCII
            else packet
        )

    def _fields(self, angles):
        yaw, pitch, roll = angles
        if self.data_mode is DataMode.EULER:
            if self.version_info.inverts_yaw:
                yaw = -yaw
            return [self._fixed(value) for value in (yaw, pitch, roll)]
        magnetic = magnetic_from_orientation(yaw, pitch, roll, self.dip) * FIXED_ONE
        fields = [int(round(value)) for value in magnetic] + [
            self._fixed(pitch),
            self._fixed(roll),
        ]
        if self.data_mode is DataMode.RAW:
            return [
                int(np.clip(round(value / 16) + RAW_CENTRE, 0, RAW_FULL_SCALE))
                for value in fields
            ]
        return fields

    @staticmethod
    def _fixed(degrees):
        return int(np.clip(round(degrees / DEGREES_PER_UNIT), *INT16))

    def _mouse_packet(self, angles):
        """Turn the change in yaw and pitch into mickeys, as mouse mode does."""
        yaw, pitch = angles[0], angles[1]
        if self._last_angles is None:
            self._last_angles = (yaw, pitch)
            return None
        moved = np.array([yaw - self._last_angles[0], pitch - self._last_angles[1]])
        self._last_angles = (yaw, pitch)
        if not self.sensitivity:
            return None
        scale = np.array(
            [
                MICKEY_YAW_DEGREES * self.sensitivity,
                MICKEY_PITCH_DEGREES * self.sensitivity,
            ]
        )
        self._mouse_residual += moved / scale
        mickeys = np.trunc(self._mouse_residual).astype(int)
        if np.abs(mickeys).max() <= self.threshold:
            return None
        self._mouse_residual -= mickeys
        return frame_mouse(-mickeys[0], -mickeys[1])
