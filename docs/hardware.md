# i-glasses! hardware

Summary of the parts of the Virtual i-O i-glasses! that this package targets. All of it
is drawn from the i-glasses! Developer Kit v1.2 (Virtual i-O, 1995), sections B, D and
E, and from contemporary 1995 Usenet material. Those documents are third party and are
neither redistributed nor quoted here.

## Display

The headset is a pair of independent colour LCD panels with stereo headphones, driven
from a single standard composite video input plus two audio wires. NTSC sets shipped
first; PAL sets followed. Because the input is ordinary broadcast-standard composite,
the signal is always interlaced, and any source that can produce compliant composite
video - a VCR, a console, a computer with an NTSC or PAL encoder - can drive the
headset directly (section D).

Panel resolution is quoted in section E as 180,000 sub-pixels, i.e. 256x230 addressable
triads, which is stated to comfortably support 320x200 computer modes. Field of view is
roughly 40 degrees. Both numbers matter for authoring: the panels resolve far less than
a full NTSC or PAL field, and the narrow field of view means comfortable parallax is a
small number of output pixels, so heavy convergence offsets are unnecessary and quickly
become uncomfortable.

## Field sequential stereo separation

Stereo separation happens inside the headset, not in the source. The video hardware
routes one field of the interlaced signal to the left panel and the other to the right.
Section E defines the left eye as the first scanline of the first field - the one
closest to the top of the screen - which makes top field first the correct field order
for any file intended for the headset. This is the same convention used by commercially
produced field sequential stereoscopic 3D videotape, so such tapes play correctly with
no conversion.

The set carries a switch that exchanges the two panels. It exists so that material
authored with the opposite field assignment can be watched without re-encoding, and it
means an author does not have to be certain of the convention at authoring time. The
encoder's `--swap-eyes` option does the same thing in software.

## Other display modes

Beyond composite, the PC version's converter box accepts VGA input. Section E lists VGA
modes 1h-13h including unchained ("mode X") variants, 60 and 70 Hz vertical refresh
(449 or 525 total lines), and 15.75-31.5 kHz horizontal refresh.

Two non-composite stereo modes are supported. In *frame sequential* mode the host
renders each eye to its own page and flips pages on the vertical retrace at 60 Hz; the
left eye is undefined in this mode, so the eyes may need swapping at the headset. In
*interleaved VGA* mode the two eyes share one framebuffer on alternate scanlines, and
here the left eye is the first scanline, matching the composite convention. The listed
interleaved modes are 640x480 (640x240 per eye), 640x400 (640x200 per eye), 320x400
(320x200 per eye) and interleaved Enigma 320x200 (320x100 per eye).

Section E also notes that hardware 3D multiplexers, which combine two full video frames
into one field sequential signal, existed for NTSC and PAL but not for VGA. This package
does that multiplexing in software.

## Head tracker

The head tracker is a separate device reporting yaw, pitch and roll over a three-wire
RS-232C interface (TXD, RXD, GND) at 1200, 2400, 4800, 9600 or 19200 bps, with rate
auto-detection and no user-set switches. Section D notes that 9600 and 19200 bps give
response times under about 15 ms. The line format is one start bit, eight data bits, no
parity, one stop bit. Positive yaw is a left head rotation, positive pitch an upward
tilt, positive roll a left tilt, in a right-handed coordinate system with +Y up, +Z out
and +X right (section B).

The command set is printable ASCII. Commands other than the send command begin with an
attention character and end with a carriage return, and the tracker acknowledges each
with a single character indicating success or error. There are commands to reset the
tracker to its default state, to read a structured version string identifying
manufacturer, product, type, and hardware and firmware revisions, and to select the
data mode, send mode (polled or continuous), numeric format (binary or ASCII) and the
magnetic and tilt filter strengths.

Five data modes are defined (section B):

* mode 0, raw sensor readings, for hardware debugging;
* mode 1, cooked, with the magnetic vector centred and the tilt sensors linearised
  against factory calibration;
* mode 2, Euler angles, yaw/pitch/roll as scaled signed 16-bit words;
* mode 3, Microsoft mouse emulation, at 1200 bps, with configurable sensitivity and
  threshold, for games with no native tracker support;
* mode 4, CyberMaxx emulation, listed as not implemented in this firmware revision.

Binary packets in modes 0-2 begin with a fixed header byte and end with an arithmetic
checksum over the preceding bytes; continuous mode requires resynchronising on the
header and validating the checksum, and the developer kit recommends polled mode for
production use.

Section B also documents a firmware erratum: trackers with firmware earlier than
revision 001.003 report the wrong sign for yaw in Euler mode, so a driver should read
the version string and correct for it.

`pyiglasses.tracker` implements this - the serial transport, the rate sweep and reset
handshake, packet framing and checksum validation for modes 0-2, host-side yaw for
cooked mode, mouse packet decoding, and the version-dependent yaw sign correction - and
`iglasses track` drives it from the command line. A software tracker that speaks the
same protocol is included, so the driver runs with no hardware attached. See
[tracker.md](tracker.md) for the protocol details and the driver's conventions.
