"""Command line entry point."""

import argparse
import sys
from contextlib import ExitStack
from fractions import Fraction

from .encode import DEFAULT_PROFILE, PROFILES, InterlacedWriter, get_profile
from .formats import DEFAULT_FORMAT, FORMATS, get_format
from .pattern import frame as pattern_frame
from .pipeline import encode_stereo
from .stereo import DEFAULT_LAYOUT, LAYOUTS
from .tracker import (
    BAUD_RATES,
    DataMode,
    SendFormat,
    SendMode,
    SimulatedTracker,
    Tracker,
)
from .tracker.device import SerialTransport
from .verify import verify
from .weave import FITS, Geometry
from .resample import KERNELS


def _geometry(args):
    return Geometry(
        fit=args.fit,
        overscan=args.overscan,
        convergence=args.convergence,
        kernel=args.kernel,
    )


def _add_output_options(parser):
    parser.add_argument(
        "-f", "--format", default=DEFAULT_FORMAT, choices=sorted(FORMATS)
    )
    parser.add_argument(
        "-p", "--profile", default=DEFAULT_PROFILE, choices=sorted(PROFILES)
    )
    parser.add_argument(
        "--swap-eyes", action="store_true", help="put the right eye on the first field"
    )


def _cmd_encode(args):
    result = encode_stereo(
        args.input,
        args.output,
        right_source=args.right,
        layout=args.layout,
        video_format=args.format,
        profile=args.profile,
        geometry=_geometry(args),
        swap_eyes=args.swap_eyes,
        eye_aspect=(
            Fraction(args.eye_aspect.replace(":", "/")) if args.eye_aspect else None
        ),
        audio=not args.no_audio,
        max_frames=args.frames,
    )
    print(
        f"{result.path}: {result.frames} frames, {result.duration:.2f}s, "
        f"{result.video_format.name} {result.profile}, "
        f"eye {result.eye_size[1]}x{result.eye_size[0]} at {result.eye_aspect} "
        f"into {result.rect[2]}x{result.rect[3]} at {result.rect[0]},{result.rect[1]}"
    )
    return 0


def _cmd_pattern(args):
    fmt = get_format(args.format)
    profile = get_profile(args.profile)
    image = pattern_frame(fmt, args.swap_eyes)
    count = max(1, round(args.duration * float(fmt.rate)))
    with InterlacedWriter(args.output, fmt, profile) as writer:
        for _ in range(count):
            writer.write(image)
    print(f"{args.output}: {count} frames of {fmt.name} test pattern")
    return 0


def _cmd_verify(args):
    failed = 0
    for path in args.input:
        report = verify(path, max_frames=args.frames)
        print("\n".join(report.lines()))
        failed |= not report.ok
    return int(failed)


TRACK_MODES = {
    "raw": DataMode.RAW,
    "cooked": DataMode.COOKED,
    "euler": DataMode.EULER,
    "mouse": DataMode.MOUSE,
}


def _pair(text, name):
    """Parse a "a,b" option into two integers."""
    try:
        first, second = (int(part) for part in text.split(","))
    except ValueError:
        raise ValueError(
            f"--{name} wants two numbers separated by a comma, got {text!r}"
        ) from None
    return first, second


def _open_tracker(args):
    """Connect to a tracker, or to the built in simulator."""
    transport = SimulatedTracker() if args.simulate else SerialTransport(args.port)
    tracker = Tracker(transport, timeout=args.timeout)
    rates = BAUD_RATES if args.baud is None else (args.baud,)
    rate = tracker.negotiate(rates)
    if rate is None:
        raise OSError(f"no tracker answered at any of {list(rates)}")
    return tracker, rate


def _cmd_track(args):
    if not args.simulate and not args.port:
        raise ValueError("give --port, or --simulate to use the built in tracker")
    tracker, rate = _open_tracker(args)
    with tracker:
        info = tracker.version()
        print(
            f"{info.manufacturer} {info.product} type {info.product_type} "
            f"hardware {info.hardware:07.3f} firmware {info.firmware:07.3f} at {rate} bps, "
            f"self test {'passed' if info.self_test_passed else 'FAILED'}"
        )
        if info.inverts_yaw:
            print("firmware predates 001.003: correcting the Euler mode yaw sign")
        if args.info:
            return 0
        mode = TRACK_MODES[args.mode]
        send = SendMode.CONTINUOUS if args.continuous else SendMode.POLLED
        if mode is DataMode.MOUSE:
            send = SendMode.MOUSE_DELTA if args.continuous else SendMode.POLLED
        filters = _pair(args.filter, "filter") if args.filter else (None, None)
        mouse = _pair(args.mouse, "mouse") if args.mouse else (None, None)
        tracker.configure(
            mode, send, SendFormat(args.format[0].upper()), *filters, *mouse
        )
        readings = (
            tracker.stream(limit=args.samples)
            if args.continuous
            else _polled(tracker, args)
        )
        _report(readings, mode, args.csv)
    return 0


def _polled(tracker, args):
    count = 0
    while args.samples is None or count < args.samples:
        yield tracker.poll()
        count += 1


def _report(readings, mode, csv_path):
    """Print readings, and optionally write them as CSV."""
    if mode is DataMode.MOUSE:
        header = "dx,dy,left,right"
    elif mode is DataMode.RAW:
        header = "x,y,z,pitch,roll"
    else:
        header = "yaw,pitch,roll"
    with ExitStack() as stack:
        handle = (
            stack.enter_context(open(csv_path, "w", encoding="ascii"))
            if csv_path
            else None
        )
        if handle:
            handle.write(header + "\n")
        try:
            for reading in readings:
                values = _reading_values(reading, mode)
                print("  ".join(_column(value) for value in values))
                if handle:
                    handle.write(",".join(str(value) for value in values) + "\n")
        except KeyboardInterrupt:
            pass


def _column(value):
    """Format one reading column."""
    return f"{value:9.3f}" if isinstance(value, float) else f"{value:>9}"


def _reading_values(reading, mode):
    if mode is DataMode.MOUSE:
        return [reading.delta_x, reading.delta_y, int(reading.left), int(reading.right)]
    if mode is DataMode.RAW:
        return list(reading.fields)
    return [float(value) for value in reading.angles]


def _cmd_formats(_args):
    print("formats:")
    for fmt in FORMATS.values():
        print(
            f"  {fmt.name:12s} {fmt.width}x{fmt.height} {float(fmt.rate):.3f} fps interlaced, "
            f"{fmt.field_height} lines per eye, display {fmt.display_aspect}"
        )
    print("profiles:")
    for profile in PROFILES.values():
        print(
            f"  {profile.name:12s} {profile.codec} {profile.pix_fmt} in {profile.extension}"
        )
    print(f"layouts:\n  {' '.join(sorted(LAYOUTS))}")
    return 0


def build_parser():
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="iglasses",
        description="Field sequential 3D tools for Virtual i-O i-glasses!",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    encode = sub.add_parser("encode", help="encode a stereo source for the glasses")
    encode.add_argument(
        "input", help="packed stereo file, or the left eye with --right"
    )
    encode.add_argument("-o", "--output", required=True)
    encode.add_argument("--right", help="right eye file, implies --layout separate")
    encode.add_argument(
        "-l", "--layout", default=DEFAULT_LAYOUT, choices=sorted(LAYOUTS)
    )
    encode.add_argument("--fit", default="contain", choices=list(FITS))
    encode.add_argument(
        "--overscan", type=float, default=0.0, help="crop this fraction off each edge"
    )
    encode.add_argument(
        "--convergence",
        type=int,
        default=0,
        help="add this many pixels of disparity; positive sits behind the screen",
    )
    encode.add_argument("--kernel", default="lanczos", choices=sorted(KERNELS))
    encode.add_argument("--eye-aspect", help="display aspect of one eye, e.g. 16:9")
    encode.add_argument("--no-audio", action="store_true")
    encode.add_argument("--frames", type=int, help="stop after this many output frames")
    _add_output_options(encode)
    encode.set_defaults(func=_cmd_encode)

    pattern = sub.add_parser("pattern", help="write a stereo test pattern")
    pattern.add_argument("-o", "--output", required=True)
    pattern.add_argument("-d", "--duration", type=float, default=10.0, help="seconds")
    _add_output_options(pattern)
    pattern.set_defaults(func=_cmd_pattern)

    check = sub.add_parser(
        "verify", help="check an encoded file is field sequential 3D"
    )
    check.add_argument("input", nargs="+")
    check.add_argument("--frames", type=int, default=32, help="frames to inspect")
    check.set_defaults(func=_cmd_verify)

    track = sub.add_parser("track", help="read the head tracker")
    track.add_argument("-P", "--port", help="serial port, e.g. /dev/ttyUSB0")
    track.add_argument(
        "--simulate", action="store_true", help="use the built in tracker simulator"
    )
    track.add_argument(
        "--baud", type=int, choices=BAUD_RATES, help="skip the rate scan"
    )
    track.add_argument("-m", "--mode", default="euler", choices=sorted(TRACK_MODES))
    track.add_argument("--format", default="binary", choices=["binary", "ascii"])
    track.add_argument(
        "--continuous", action="store_true", help="stream instead of polling"
    )
    track.add_argument("--filter", help="magnetic,tilt filter strengths, each 0-7")
    track.add_argument("--mouse", help="mouse sensitivity,threshold, each 0-9")
    track.add_argument(
        "-n", "--samples", type=int, help="stop after this many readings"
    )
    track.add_argument("--csv", help="also write the readings to this file")
    track.add_argument(
        "--timeout", type=float, default=2.0, help="seconds to wait for a reply"
    )
    track.add_argument(
        "--info", action="store_true", help="report the version and stop"
    )
    track.set_defaults(func=_cmd_track)

    listing = sub.add_parser("formats", help="list formats, profiles and layouts")
    listing.set_defaults(func=_cmd_formats)
    return parser


def main(argv=None):
    """Run the command line tool."""
    args = build_parser().parse_args(argv)
    if getattr(args, "right", None) and args.layout != "separate":
        args.layout = "separate"
    try:
        return args.func(args)
    except (ValueError, OSError) as error:
        print(f"iglasses: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
