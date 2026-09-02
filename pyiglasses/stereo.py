"""Stereo source layouts and eye geometry deduction."""

from dataclasses import dataclass
from fractions import Fraction

# Display aspect ratios stereo material is authored to.
STANDARD_ASPECTS = tuple(
    Fraction(n).limit_denominator(1000)
    for n in (4 / 3, 16 / 9, 16 / 10, 5 / 4, 1.85, 2.35, 2.39, 1.0)
)


@dataclass(frozen=True)
class Layout:
    """How the two eyes are packed into a decoded frame."""

    name: str
    axis: int | None

    def split(self, frame):
        """Return (left, right) views of a packed frame."""
        if self.axis is None:
            raise ValueError(f"layout {self.name!r} takes two separate inputs")
        half = frame.shape[self.axis] // 2
        if self.axis == 1:
            return frame[:, :half], frame[:, half : 2 * half]
        return frame[:half], frame[half : 2 * half]

    def eye_shape(self, height, width):
        """Return the (height, width) of one eye in a packed frame."""
        if self.axis == 1:
            return height, width // 2
        if self.axis == 0:
            return height // 2, width
        return height, width


LAYOUTS = {
    layout.name: layout
    for layout in (
        Layout("sbs", 1),
        Layout("ou", 0),
        Layout("separate", None),
    )
}

DEFAULT_LAYOUT = "sbs"


def get_layout(name: str) -> Layout:
    """Look up a layout by name."""
    try:
        return LAYOUTS[name]
    except KeyError:
        raise ValueError(
            f"unknown layout {name!r}, want one of {sorted(LAYOUTS)}"
        ) from None


def deduce_eye_aspect(eye_height, eye_width, sample_aspect=Fraction(1), layout=None):
    """Deduce the display aspect ratio of one eye.

    Half packed material (the common case) squeezes a full aspect image into
    half a frame, so the pixel dimensions of an eye alone are ambiguous: a
    960x1080 half of a side by side frame and a 1920x1080 half of a full width
    one are both 16:9 pictures.  Both readings are scored against the aspects
    real material is authored to and the closer one wins.
    """
    literal = Fraction(eye_width, eye_height) * Fraction(sample_aspect)
    candidates = [literal]
    if layout is not None and layout.axis == 1:
        candidates.append(literal * 2)
    elif layout is not None and layout.axis == 0:
        candidates.append(literal / 2)
    return min(
        candidates,
        key=lambda dar: min(abs(float(dar / std) - 1.0) for std in STANDARD_ASPECTS),
    )
