# Head tracker notes

References are to the i-glasses! Developer Kit v1.2 (Virtual i-O, 1995), sections B and
C. That document is third party and is not redistributed here. The device itself is
described in [hardware.md](hardware.md); this file covers the driver in
`pyiglasses/tracker` and the `iglasses track` command.

## Serial protocol

Three wires (TXD, RXD, GND), one start bit, eight data bits, no parity, one stop bit, at
1200, 2400, 4800, 9600 or 19200 bps. The tracker auto-detects the host's rate, so there
is nothing to set on the device.

Commands are printable ASCII. Every command except `S` begins with `!` and ends with a
carriage return, and the tracker answers with a single `O` for ok or `E` for an error.
`S` is unterminated: in a polled mode it asks for one packet, and in a continuous mode
it starts the stream. A bare `!` stops a running stream, so `!` plus a carriage return
is both a stop and a no-op command that must be acknowledged.

`protocol.py` builds the three commands the driver uses - `!R` (reset to cooked, polled,
binary), `!V` (revision string and self test result) and `!M` (data mode, send mode,
send format, and optionally the two filter strengths and then the two mouse settings).
`mode_command` enforces the ordering rule: filters may be given alone, mouse settings
may not be given without them.

## Connecting is a rate sweep

The tracker keeps its data mode, send mode and send format across a power cycle, so a
host that has just opened the port knows nothing: the device may be idle, or streaming
binary packets, at any of the five rates. Section B's remedy is to send reset commands
until one is acknowledged.

`Tracker.reset` does one rate: stop the stream, drop whatever is buffered, write `!R`,
and read until an `O` or `E` appears, up to three attempts. Reading until a result code
appears rather than parsing a fixed reply is what makes this work against a tracker that
is still emitting packets from a stream that has only just been told to stop.

`Tracker.negotiate` walks the rates, fastest first, and returns the one that answered;
`Tracker.connect` opens a port and does that, and `iglasses track` does it at startup.
`--baud` restricts the sweep to a single rate when the tracker's rate is already known.

## Data modes

| mode | name | packet | contents |
| --- | --- | --- | --- |
| 0 | raw | 12 bytes | unfiltered sensor counts, 12 bits unsigned in 16 bit fields |
| 1 | cooked | 12 bytes | scaled magnetic vector plus linearised pitch and roll |
| 2 | euler | 8 bytes | yaw, pitch and roll computed on the tracker |
| 3 | mouse | 3 bytes | Microsoft mouse packets |
| 4 | CyberMaxx | - | listed in the developer kit, never implemented in firmware |

Use Euler mode unless you have a reason not to: it is the device-independent interface,
and the tracker does the sensor fusion. Use cooked mode when you want the magnetic
vector itself, or want to filter or fuse it on the host. Raw mode is for hardware
debugging - the developer kit says factory debugging only, and there is no calibration
behind the numbers, so `decode_angles` returns no angles for it. Mouse mode is for
software with no native tracker support.

Mode 4 is not implemented by any shipped firmware. The driver has no packet size for it,
and the simulator rejects a `!M4,...` command with `E`.

Orthogonal to the data mode are the send mode - `P` polled, `C` continuous, or `0`/`1`
in mouse mode - and the send format, `B` for binary or `A` for space separated ASCII
hex. ASCII is a debugging format. The developer kit recommends polled mode for
production: a continuous stream is harder to recover from an error and spends interrupts
on data nobody asked for.

## Packet framing

A binary packet is a 255 header, big endian 16 bit fields, and an arithmetic checksum of
every preceding byte taken modulo 256. Raw and cooked packets carry x, y, z, pitch and
roll; Euler packets carry yaw, pitch and roll.

The header is not unique - any field byte can be 255 - so a header is only a candidate.
Section B's rule is to validate the checksum and, when it fails, resume the search one
byte past that header rather than past the whole candidate packet. Doing that one packet
at a time is a byte loop, so `find_packets` does the whole buffer at once: a single
cumulative sum gives any candidate's checksum as a difference of two entries, every
header position is tested in one vectorised comparison, and the survivors are then swept
once to drop overlaps. A false header inside a real packet fails the comparison and
costs nothing.

`PacketReader.feed` decides every start position for which a whole packet's worth of
bytes has arrived, so the only thing ever carried across a read is a trailing fragment
shorter than one packet; the buffer cannot grow without bound however much garbage
arrives. `discarded` counts the bytes that were never part of a valid packet.

The ASCII form is the same packet as hex tokens. `parse_ascii_packet` accepts any token
width, so a tracker that groups its hex by byte and one that groups by 16 bit field both
decode, and the header and checksum are still checked.

## Fixed point

Angles are a signed 16 bit field in which `1 << 14` is 180 degrees, so degrees are
`reading * 180 / 16384` and the field reaches a full turn either way before it
saturates. Cooked magnetic components use the same scale and are divided by `1 << 14` on
decode, which puts them near unit length; their true magnitude varies with the Earth's
field. Raw mode is the exception: its fields are 12 bit unsigned counts, decoded as
unsigned.

## Cooked mode: yaw is the host's problem

Cooked mode gives a magnetic vector, scaled and centred about zero, plus pitch and roll
linearised against the tracker's factory calibration. It does not give yaw. Yaw comes
from the magnetic vector, tilt-compensated with the pitch and roll the tracker just
reported: undo the roll about +Z, undo the pitch about +X, and take the bearing of what
is left in the horizontal plane. That is `packets.tilt_compensated_yaw`, and it is
applied to a whole capture at once rather than per sample.

The convention it assumes:

* axes are +X right, +Y up and +Z out of the face, right handed;
* positive yaw is a left head rotation, positive pitch an upward tilt, positive roll a
  left tilt (section B);
* the body frame is reached by yawing, then pitching, then rolling;
* the world field points north and dips downwards, 65 degrees by default.

`packets.magnetic_from_orientation` is the exact inverse of that function and is the
explicit statement of the model - it is what the simulator uses to synthesise cooked and
raw packets from an orientation.

**This convention has been verified only for internal consistency.** The tests check it
against rotation matrices written out independently of the driver, check that the
forward and inverse functions agree to numerical precision, and check that a simulated
capture decodes back to the orientation it was generated from. None of that is evidence
about real hardware: the developer kit does not pin down how the magnetometer axes are
labelled relative to the tilt sensors, so a sign or an axis swap would survive every
test here. Anyone with a real tracker should read the same movement in Euler mode and in
cooked mode and compare the two yaw figures, and report a discrepancy. Euler mode is
unaffected either way, because the tracker computes yaw itself.

## Firmware erratum: the Euler yaw sign

Firmware revisions before 001.003 report the wrong sign for yaw in Euler mode; 001.003
(25 April 1995) fixed it. Section B's instruction is to read the version string and
correct for it in the application.

`Tracker.version` parses the `!V` reply into a `VersionInfo`, and sets `Tracker.yaw_sign`
to -1 when the firmware predates 001.003. `decode_angles` multiplies Euler mode yaw by
it, and `iglasses track` prints a line saying the correction is in force. The driver
reads the version before it configures anything, so the correction is always in place
before the first reading.

The correction applies to Euler mode only. The erratum is a bug in the tracker's own
Euler computation; cooked mode yaw is computed on the host from a magnetic vector the
erratum never touched, so correcting it there would invert a reading that was already
right. Both modes therefore agree on a pre-001.003 tracker as well as on a later one.

## Mouse emulation

Mouse mode makes the tracker look like a Microsoft serial mouse, so that software with
no native tracker support - 1995 first person games, in practice - can be driven by head
movement. X comes from a scaled yaw angle and Y from a scaled pitch angle. There are no
buttons, so the tracker cannot replace a pointing device, only sit alongside one.

The mode runs at 1200 bps in binary, which means the `!M3,...` command has to be sent at
1200 bps to put the tracker there. Packets are the three byte Microsoft format with bit
7 set on every byte, so that a receiver configured for seven data bits reads that bit as
a stop bit. `packets.decode_mouse` and `packets.frame_mouse` handle the bit packing;
`Tracker` resynchronises on the sync bit in the first byte rather than on a checksum,
since mouse packets have none.

Send mode `0` sends deltas for as long as the tracker keeps moving. Send mode `1` takes
a reference position when the mode is entered and sends deltas continuously until the
tracker is moved back within the threshold of it. Sensitivity and threshold both range
0-9; a sensitivity of 0 disables that axis, and the threshold sets how far the tracker
must move before a packet is emitted, applied after sensitivity scaling.

The mickey rule at sensitivity 1 is one X mickey per quarter degree of yaw and one Y
mickey per degree of pitch. **The developer kit's account of sensitivity is
self-contradictory**: it states that sensitivity 2 means a half degree change in yaw per
mickey, and in the same paragraph that the change per degree increases with sensitivity.
Those are opposite - a half degree per mickey is fewer mickeys per degree, i.e. a less
sensitive device. The simulator implements the numeric reading: degrees per mickey scale
with sensitivity, so a higher setting yields fewer mickeys for the same head movement.
The driver takes no position - it passes sensitivity and threshold through to the
tracker unchanged and never scales a delta itself - so real hardware behaves however its
firmware behaves regardless of which reading was intended.

## The simulator

`SimulatedTracker` is a transport, not a mock. It consumes the real command bytes,
answers with the real result codes, formats a real version string, and frames real
packets, so `Tracker` is exercised end to end - rate sweep, reset handshake, mode
command, framing, decode - with no hardware. The hardware is thirty years old and
scarce; this is what the driver is developed against.

Its constructor exposes the states that are otherwise hard to reach: `firmware` selects
whether the Euler yaw erratum is present, `self_test` fails the self test,
`device_baudrate` differing from `baudrate` makes it deaf until the sweep finds it,
`dip` sets the magnetic dip angle, and `orientation` is any callable from a sample index
to yaw, pitch and roll (the default is a slow repeatable sweep). Every command it
received is kept in `commands`.

Cooked and Euler packets are generated from the orientation through
`magnetic_from_orientation`, so they are exactly consistent with the decoder's model -
which is why the round trip proves internal consistency and nothing more. Raw mode
counts are that same vector rescaled into 12 bit unsigned counts about mid scale: a
plausible stand-in, not a model of the real sensors.

## Command line

```sh
# identify the tracker and stop
iglasses track --simulate --info
iglasses track -P /dev/ttyUSB0 --info

# five polled Euler readings (the default mode)
iglasses track --simulate -n 5

# cooked mode, continuous, yaw computed on the host
iglasses track --simulate -m cooked --continuous -n 3

# medium filtering, ASCII packets, to a CSV as well as the terminal
iglasses track --simulate -m euler --filter 3,3 --format ascii -n 20 --csv track.csv

# raw sensor counts, for hardware debugging only
iglasses track --simulate -m raw -n 2

# mouse emulation deltas
iglasses track --simulate -m mouse --continuous --filter 3,3 --mouse 4,1 -n 5

# a real tracker whose rate is already known, skipping the sweep
iglasses track -P /dev/ttyUSB0 --baud 19200 -m euler --continuous
```

`--simulate` swaps the serial port for `SimulatedTracker`, so every example above runs
without hardware. `-n` bounds the number of readings; without it the command runs until
interrupted. `--timeout` sets how long to wait for a reply before giving up.

## Python

```python
from pyiglasses.tracker import DataMode, SendFormat, SendMode, Tracker

with Tracker.connect("/dev/ttyUSB0") as tracker:
    print(tracker.version())
    tracker.configure(DataMode.EULER, SendMode.CONTINUOUS, SendFormat.BINARY)
    for sample in tracker.stream(limit=100):
        print(sample.angles)
```

`Tracker.connect` sweeps the rates and raises `TrackerError` if nothing answers; pass a
`SimulatedTracker` to `Tracker` directly to do the same without a port. `poll` returns
one `Sample`, `stream` yields them from a continuous mode, and both raise
`TrackerTimeout` if nothing arrives in time. A `Sample` carries the decoded `fields`,
`angles` in degrees (None in raw mode) and, in raw and cooked modes, the `magnetic`
vector.
