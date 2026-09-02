"""Talking to an i-glasses! Tracker over a serial port.

The tracker keeps its last mode across power cycles and may already be streaming
at any of its rates, so a driver cannot assume anything about the state it finds.
Section B's advice is to stop the stream and reset until the tracker answers, and
that is what :meth:`Tracker.connect` does, sweeping the rates until one replies.
"""

import time
from dataclasses import dataclass

from .packets import (
    MOUSE_PACKET_SIZE,
    MOUSE_SYNC,
    PacketReader,
    decode_mouse,
    decode_samples,
    parse_ascii_packet,
)
from .protocol import (
    BAUD_RATES,
    ERROR,
    OK,
    SEND,
    VERSION_LENGTH,
    DataMode,
    SendFormat,
    SendMode,
    mode_command,
    packet_size,
    parse_version,
    reset_command,
    stop_command,
    version_command,
)

DEFAULT_TIMEOUT = 2.0
RESET_ATTEMPTS = 3


class TrackerError(Exception):
    """The tracker refused a command or answered with something unusable."""


class TrackerTimeout(TrackerError):
    """The tracker did not answer in time."""


@dataclass(frozen=True)
class MouseSample:
    """One Microsoft mouse packet from an emulation mode."""

    delta_x: int
    delta_y: int
    left: bool
    right: bool


class SerialTransport:
    """A pyserial port, in the shape the tracker driver expects.

    Section B fixes the line format at eight data bits, no parity, one stop bit.
    A port containing ``://`` is opened as a pyserial URL, so ``loop://`` and
    ``socket://host:port`` work as well as a device node.
    """

    def __init__(self, port, baudrate=BAUD_RATES[1], read_timeout=0.05):
        import serial  # pylint: disable=import-outside-toplevel

        settings = {"baudrate": baudrate, "bytesize": 8, "parity": "N", "stopbits": 1}
        if "://" in str(port):
            self._serial = serial.serial_for_url(
                str(port), timeout=read_timeout, **settings
            )
        else:
            self._serial = serial.Serial(port=port, timeout=read_timeout, **settings)

    @property
    def baudrate(self):
        """The rate the host is talking at."""
        return self._serial.baudrate

    @baudrate.setter
    def baudrate(self, value):
        self._serial.baudrate = value

    def read(self, size):
        """Read up to ``size`` bytes, returning early on the port timeout."""
        return self._serial.read(size)

    def write(self, data):
        """Write bytes to the port."""
        return self._serial.write(data)

    def reset_input_buffer(self):
        """Throw away anything already received."""
        self._serial.reset_input_buffer()

    def close(self):
        """Close the port."""
        self._serial.close()


class Tracker:
    """Driver for the i-glasses! head tracker."""

    def __init__(self, transport, timeout=DEFAULT_TIMEOUT, clock=time.monotonic):
        self.transport = transport
        self.timeout = timeout
        self._clock = clock
        self.data_mode = DataMode.COOKED
        self.send_mode = SendMode.POLLED
        self.send_format = SendFormat.BINARY
        self.version_info = None
        self.yaw_sign = 1
        self._reader = PacketReader(self.data_mode)
        self._line = bytearray()
        self._streaming = False

    @classmethod
    def connect(cls, port, rates=BAUD_RATES, timeout=DEFAULT_TIMEOUT, **kwargs):
        """Open a serial port, find the tracker's rate and reset it."""
        transport = SerialTransport(port, **kwargs)
        tracker = cls(transport, timeout=timeout)
        if tracker.negotiate(rates) is None:
            transport.close()
            raise TrackerError(f"no tracker answered on {port} at any of {list(rates)}")
        return tracker

    def close(self):
        """Stop any stream and close the transport."""
        try:
            self.stop()
        except (TrackerError, OSError):
            pass
        self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def negotiate(self, rates=BAUD_RATES):
        """Try each rate until the tracker resets, and return the one that worked."""
        for rate in rates:
            self.transport.baudrate = rate
            if self.reset():
                return rate
        return None

    def reset(self, attempts=RESET_ATTEMPTS):
        """Stop any stream and reset to cooked, polled, binary."""
        for _ in range(attempts):
            self.stop()
            self.transport.write(reset_command())
            if self._result():
                self.data_mode = DataMode.COOKED
                self.send_mode = SendMode.POLLED
                self.send_format = SendFormat.BINARY
                self._reader = PacketReader(self.data_mode)
                return True
        return False

    def stop(self):
        """Stop a continuous stream and drop anything buffered."""
        self.transport.write(stop_command())
        self._streaming = False
        self._drain()
        self._reader.reset()
        self._line.clear()

    def version(self):
        """Read the revision string, and adopt its yaw sign correction."""
        self._drain()
        self.transport.write(version_command())
        data = bytearray()
        deadline = self._clock() + self.timeout
        while self._clock() < deadline:
            data += self.transport.read(VERSION_LENGTH * 2)
            for offset in (
                index for index, char in enumerate(data) if char == ord("M")
            ):
                if len(data) - offset < VERSION_LENGTH:
                    break
                try:
                    info = parse_version(bytes(data[offset : offset + VERSION_LENGTH]))
                except ValueError:
                    continue
                self.version_info = info
                self.yaw_sign = info.yaw_sign
                return info
        raise TrackerTimeout("no usable version string came back")

    def configure(
        self,
        data_mode=DataMode.EULER,
        send_mode=SendMode.POLLED,
        send_format=SendFormat.BINARY,
        magnetic_filter=None,
        tilt_filter=None,
        sensitivity=None,
        threshold=None,
    ):
        """Put the tracker into a data mode, and follow it locally."""
        command = mode_command(
            data_mode,
            send_mode,
            send_format,
            magnetic_filter,
            tilt_filter,
            sensitivity,
            threshold,
        )
        self._drain()
        self.transport.write(command)
        if not self._result():
            raise TrackerError(f"tracker rejected {command!r}")
        self.data_mode = DataMode(data_mode)
        self.send_mode = SendMode(send_mode)
        self.send_format = SendFormat(send_format)
        self._streaming = False
        self._line.clear()
        if self.data_mode in (DataMode.RAW, DataMode.COOKED, DataMode.EULER):
            self._reader = PacketReader(self.data_mode)
        return self

    def poll(self, timeout=None):
        """Ask for one reading and return it."""
        self.transport.write(SEND)
        return self._receive(self._deadline(timeout))

    def stream(self, limit=None, timeout=None):
        """Start a continuous stream and yield readings from it."""
        if self.send_mode is SendMode.POLLED:
            raise TrackerError("stream() needs a continuous or mouse send mode")
        if not self._streaming:
            self.transport.write(SEND)
            self._streaming = True
        count = 0
        while limit is None or count < limit:
            yield self._receive(self._deadline(timeout))
            count += 1

    def _deadline(self, timeout):
        return self._clock() + (self.timeout if timeout is None else timeout)

    def _receive(self, deadline):
        if self.data_mode in (DataMode.MOUSE, DataMode.CYBERMAXX):
            return self._receive_mouse(deadline)
        if self.send_format is SendFormat.ASCII:
            return self._receive_ascii(deadline)
        return self._receive_binary(deadline)

    def _receive_binary(self, deadline):
        while True:
            packets = self._reader.feed(self._read_more(deadline))
            if packets.shape[0]:
                return decode_samples(packets[:1], self.data_mode, self.yaw_sign)[0]

    def _receive_ascii(self, deadline):
        size = packet_size(self.data_mode)
        while True:
            self._line += self._read_more(deadline)
            while True:
                end = self._line.find(b"\n")
                if end < 0:
                    end = self._line.find(b"\r")
                if end < 0:
                    break
                line, self._line = bytes(self._line[:end]), self._line[end + 1 :]
                try:
                    packet = parse_ascii_packet(line, size)
                except ValueError:
                    continue
                return decode_samples([list(packet)], self.data_mode, self.yaw_sign)[0]

    def _receive_mouse(self, deadline):
        while True:
            self._line += self._read_more(deadline)
            starts = [
                index for index, byte in enumerate(self._line) if byte & MOUSE_SYNC
            ]
            for start in starts:
                if len(self._line) - start < MOUSE_PACKET_SIZE:
                    break
                packet = bytes(self._line[start : start + MOUSE_PACKET_SIZE])
                self._line = self._line[start + MOUSE_PACKET_SIZE :]
                return MouseSample(*decode_mouse(packet))
            if starts and len(self._line) > MOUSE_PACKET_SIZE * 2:
                self._line = self._line[starts[-1] :]

    def _read_more(self, deadline, size=64):
        data = self.transport.read(size)
        if not data and self._clock() >= deadline:
            raise TrackerTimeout("the tracker sent nothing before the timeout")
        return data

    def _result(self):
        """Read until the tracker acknowledges, ignoring stream leftovers."""
        deadline = self._clock() + self.timeout
        while self._clock() < deadline:
            data = self.transport.read(64)
            if OK in data:
                return True
            if ERROR in data:
                return False
        return False

    def _drain(self):
        self.transport.reset_input_buffer()
        self._reader.reset()
        self._line.clear()
