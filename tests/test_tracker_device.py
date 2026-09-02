"""The driver, against a simulated tracker."""

import pytest

from pyiglasses.tracker.device import MouseSample, Tracker, TrackerError, TrackerTimeout
from pyiglasses.tracker.packets import MOUSE_PACKET_SIZE
from pyiglasses.tracker.protocol import (
    BAUD_RATES,
    DataMode,
    SendFormat,
    SendMode,
    mode_command,
)
from pyiglasses.tracker.simulator import SimulatedTracker, sweep


class Stopwatch:
    """A clock that only moves when it is read, so timeouts do not take time."""

    def __init__(self, step=0.05):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


@pytest.fixture(name="tracker")
def fixture_tracker():
    """A driver attached to a simulator, already reset."""
    device = Tracker(SimulatedTracker(), timeout=0.5, clock=Stopwatch())
    assert device.reset()
    return device


def test_reset_returns_the_tracker_to_the_documented_defaults(tracker):
    assert tracker.data_mode is DataMode.COOKED
    assert tracker.send_mode is SendMode.POLLED
    assert tracker.send_format is SendFormat.BINARY
    assert tracker.transport.commands[:2] == [b"", b"R"]


def test_reset_stops_a_stream_that_was_already_running():
    transport = SimulatedTracker()
    transport.send_mode = SendMode.CONTINUOUS
    transport.streaming = True
    device = Tracker(transport, timeout=0.5, clock=Stopwatch())
    assert device.reset()
    assert not transport.streaming


def test_a_tracker_at_an_unexpected_rate_is_found_by_sweeping():
    transport = SimulatedTracker(baudrate=19200, device_baudrate=2400)
    device = Tracker(transport, timeout=0.1, clock=Stopwatch())
    assert device.negotiate() == 2400
    assert transport.baudrate == 2400


def test_a_silent_port_gives_up():
    transport = SimulatedTracker(baudrate=19200, device_baudrate=110)
    device = Tracker(transport, timeout=0.1, clock=Stopwatch())
    assert device.negotiate(BAUD_RATES) is None
    assert not device.reset(attempts=1)


def test_the_version_string_is_parsed_through_stream_leftovers():
    transport = SimulatedTracker()
    device = Tracker(transport, timeout=0.5, clock=Stopwatch())
    device.reset()
    transport._output += b"junk before the answer"  # pylint: disable=protected-access
    info = device.version()
    assert info.manufacturer == "VIRTUAL I-O"
    assert device.yaw_sign == 1


def test_a_tracker_that_never_answers_times_out():
    device = Tracker(
        SimulatedTracker(device_baudrate=110), timeout=0.2, clock=Stopwatch()
    )
    with pytest.raises(TrackerTimeout):
        device.version()


@pytest.mark.parametrize("mode", [DataMode.EULER, DataMode.COOKED])
@pytest.mark.parametrize("send_format", [SendFormat.BINARY, SendFormat.ASCII])
def test_polling_returns_the_orientation_the_tracker_is_at(tracker, mode, send_format):
    tracker.configure(mode, SendMode.POLLED, send_format)
    first, second = tracker.poll(), tracker.poll()
    assert first.mode is mode
    assert first.angles == pytest.approx(sweep(0), abs=0.05)
    assert second.angles == pytest.approx(sweep(1), abs=0.05)


def test_raw_mode_returns_counts_rather_than_angles(tracker):
    tracker.configure(DataMode.RAW, SendMode.POLLED, SendFormat.BINARY)
    sample = tracker.poll()
    assert sample.angles is None
    assert len(sample.fields) == 5
    assert all(0 <= value <= 4095 for value in sample.fields)


def test_streaming_yields_consecutive_readings(tracker):
    tracker.configure(DataMode.EULER, SendMode.CONTINUOUS, SendFormat.BINARY)
    readings = list(tracker.stream(limit=5))
    assert len(readings) == 5
    assert [reading.angles[0] for reading in readings] == pytest.approx(
        [sweep(index)[0] for index in range(5)], abs=0.05
    )


def test_stopping_a_stream_leaves_the_tracker_quiet(tracker):
    tracker.configure(DataMode.EULER, SendMode.CONTINUOUS, SendFormat.BINARY)
    next(tracker.stream())
    tracker.stop()
    assert not tracker.transport.streaming


def test_streaming_needs_a_streaming_send_mode(tracker):
    with pytest.raises(TrackerError, match="continuous or mouse"):
        next(tracker.stream())


def test_mouse_mode_reports_deltas(tracker):
    tracker.configure(
        DataMode.MOUSE, SendMode.MOUSE_DELTA, SendFormat.BINARY, 3, 3, 2, 0
    )
    readings = list(tracker.stream(limit=4))
    assert all(isinstance(reading, MouseSample) for reading in readings)
    assert any(
        reading.delta_x for reading in readings
    ), "a yawing head moves the pointer"


def test_a_rejected_mode_raises(tracker):
    with pytest.raises(TrackerError, match="rejected"):
        tracker.configure(DataMode.CYBERMAXX)


def test_early_firmware_has_its_yaw_corrected():
    """The tracker sends the wrong sign; the reading that comes out is right."""
    buggy = Tracker(SimulatedTracker(firmware=1.002), timeout=0.5, clock=Stopwatch())
    buggy.reset()
    assert buggy.version().inverts_yaw
    buggy.configure(DataMode.EULER, SendMode.POLLED, SendFormat.BINARY)
    good = Tracker(SimulatedTracker(firmware=1.004), timeout=0.5, clock=Stopwatch())
    good.reset()
    good.version()
    good.configure(DataMode.EULER, SendMode.POLLED, SendFormat.BINARY)
    assert buggy.poll().yaw == pytest.approx(good.poll().yaw)


def test_closing_stops_the_stream_and_shuts_the_port(tracker):
    tracker.configure(DataMode.EULER, SendMode.CONTINUOUS, SendFormat.BINARY)
    next(tracker.stream())
    with tracker:
        pass
    assert not tracker.transport.streaming


def test_closing_survives_a_transport_that_is_already_broken(tracker):
    def explode(_data):
        raise OSError("port went away")

    tracker.transport.write = explode
    tracker.close()


def test_a_stream_that_dries_up_times_out(tracker):
    tracker.configure(DataMode.EULER, SendMode.CONTINUOUS, SendFormat.BINARY)
    tracker.transport.device_baudrate = 110
    with pytest.raises(TrackerTimeout):
        next(tracker.stream())


def test_the_simulator_refuses_commands_it_does_not_know(tracker):
    tracker.transport.write(b"!Q\r")
    assert not tracker._result()  # pylint: disable=protected-access


@pytest.mark.parametrize(
    "command", [b"!M9,P,B\r", b"!M1,X,B\r", b"!M1,P,B,9,9\r", b"!M1,P\r"]
)
def test_the_simulator_validates_mode_commands(tracker, command):
    tracker.transport.write(command)
    assert not tracker._result()  # pylint: disable=protected-access


def test_a_zero_sensitivity_disables_the_mouse(tracker):
    tracker.configure(
        DataMode.MOUSE, SendMode.MOUSE_DELTA, SendFormat.BINARY, 0, 0, 0, 0
    )
    with pytest.raises(TrackerTimeout):
        next(tracker.stream())


class Scripted:
    """A transport that plays back a fixed reply a few bytes at a time."""

    def __init__(self, data, chunk=7):
        self.data = bytearray(data)
        self.chunk = chunk
        self.written = bytearray()
        self.baudrate = 9600

    def read(self, size):
        take = min(size, self.chunk, len(self.data))
        data, self.data = bytes(self.data[:take]), self.data[take:]
        return data

    def write(self, data):
        self.written += data
        return len(data)

    def reset_input_buffer(self):
        pass

    def close(self):
        pass


def test_the_version_string_is_found_among_decoys_arriving_a_few_bytes_at_a_time():
    from pyiglasses.tracker.protocol import VersionInfo, format_version

    info = VersionInfo("VIRTUAL I-O", "0001", "TRACKER", 1.001, 1.002, True)
    decoy = b"M" + b"x" * 80
    device = Tracker(
        Scripted(decoy + format_version(info)), timeout=5.0, clock=Stopwatch()
    )
    assert device.version() == info
    assert device.yaw_sign == -1


def test_an_unparsable_ascii_line_is_skipped(tracker):
    tracker.configure(DataMode.EULER, SendMode.POLLED, SendFormat.ASCII)
    tracker.transport.inject(b"not hex at all\r\n")
    assert tracker.poll().angles == pytest.approx(sweep(0), abs=0.05)


def test_mouse_framing_resynchronises_after_line_noise(tracker):
    tracker.configure(
        DataMode.MOUSE, SendMode.MOUSE_DELTA, SendFormat.BINARY, 3, 3, 2, 0
    )
    tracker.transport.inject(b"\x80" * 6)
    assert isinstance(next(tracker.stream()), MouseSample)


def test_a_high_mouse_threshold_sends_fewer_packets():
    """The tracker must move further before it reports, so packets are rarer."""
    counts = []
    for threshold in (0, 9):
        device = SimulatedTracker()
        device.write(mode_command(DataMode.MOUSE, "0", "B", 3, 3, 1, threshold))
        device.reset_input_buffer()
        device.write(b"S")
        data = bytearray()
        for _ in range(40):
            data += device.read(64)
        counts.append(len(data) // MOUSE_PACKET_SIZE)
    assert counts[0] > counts[1] > 0


def test_a_serial_url_opens_a_real_port_object():
    from pyiglasses.tracker.device import SerialTransport

    transport = SerialTransport("loop://", read_timeout=0.01)
    try:
        transport.write(b"!R\r")
        assert transport.read(3) == b"!R\r"
        transport.baudrate = 4800
        assert transport.baudrate == 4800
        transport.reset_input_buffer()
    finally:
        transport.close()


def test_connecting_to_a_port_with_no_tracker_on_it_fails():
    with pytest.raises(TrackerError, match="no tracker answered"):
        Tracker.connect("loop://", rates=(9600,), timeout=0.05, read_timeout=0.01)
