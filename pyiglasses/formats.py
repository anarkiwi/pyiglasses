"""Interlaced video timing profiles the i-glasses! accept as composite input.

Section E of the i-glasses! Developer Kit lists NTSC composite as the native
input; PAL sets shipped later.  Both are interlaced, and stereo separation is by
field: the left eye is the first scanline of the first field.
"""

from dataclasses import dataclass
from fractions import Fraction

# AVFieldOrder values used by libavcodec.
FIELD_UNKNOWN = 0
FIELD_PROGRESSIVE = 1
FIELD_TT = 2
FIELD_BB = 3


@dataclass(frozen=True)
class VideoFormat:
    """A full-frame interlaced target format."""

    name: str
    width: int
    height: int
    rate: Fraction
    sample_aspect: Fraction
    gop_size: int

    @property
    def field_height(self) -> int:
        """Scanlines per field, i.e. per eye."""
        return self.height // 2

    @property
    def field_rate(self) -> Fraction:
        """Fields (per-eye images) per second."""
        return self.rate * 2

    @property
    def display_aspect(self) -> Fraction:
        """Aspect ratio of the displayed frame."""
        return Fraction(self.width, self.height) * self.sample_aspect


FORMATS = {
    f.name: f
    for f in (
        VideoFormat("ntsc", 720, 480, Fraction(30000, 1001), Fraction(8, 9), 15),
        VideoFormat("pal", 720, 576, Fraction(25), Fraction(16, 15), 12),
        VideoFormat("ntsc-square", 640, 480, Fraction(30000, 1001), Fraction(1), 15),
        VideoFormat("pal-square", 768, 576, Fraction(25), Fraction(1), 12),
    )
}

DEFAULT_FORMAT = "ntsc"


def get_format(name: str) -> VideoFormat:
    """Look up a format by name."""
    try:
        return FORMATS[name]
    except KeyError:
        raise ValueError(
            f"unknown format {name!r}, want one of {sorted(FORMATS)}"
        ) from None
