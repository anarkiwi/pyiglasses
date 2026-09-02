"""Weave a stereo pair into one field sequential interlaced frame.

Per the i-glasses! video specification the left eye is the first scanline of the
first field, so the left eye owns even frame lines and the right eye odd ones.
Nothing may filter vertically across the woven frame: adjacent lines are
different eyes, and averaging them is cross talk, not anti aliasing.
"""

from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from .resample import apply_matrix, resample_matrix, source_span

FITS = ("contain", "cover", "stretch")


@dataclass(frozen=True)
class Geometry:
    """Framing of the source picture inside the output raster.

    ``fit`` letterboxes (contain), crops (cover) or distorts (stretch) to the
    output aspect.  ``overscan`` crops that fraction off every edge, for sets
    that lose the border.  ``convergence`` adds that many output pixels of
    horizontal disparity: positive moves the scene behind the screen, negative
    pulls it towards the viewer.
    """

    fit: str = "contain"
    overscan: float = 0.0
    convergence: int = 0
    kernel: str = "lanczos"
    background: tuple = field(default=(0, 0, 0))

    def __post_init__(self):
        if self.fit not in FITS:
            raise ValueError(f"unknown fit {self.fit!r}, want one of {list(FITS)}")
        if not 0.0 <= self.overscan < 0.5:
            raise ValueError("overscan must be in [0, 0.5)")


def _fit_rect(src_aspect, fmt, fit):
    """Return the (x, y, width, height) of the picture in the output raster."""
    width, height = fmt.width, fmt.height
    if fit != "contain":
        return 0, 0, width, height
    target = float(fmt.display_aspect)
    if float(src_aspect) > target:
        height = int(round(fmt.height * target / float(src_aspect)))
    else:
        width = int(round(fmt.width * float(src_aspect) / target))
    height = max(2, height - height % 2)
    top = (fmt.height - height) // 2
    return (fmt.width - width) // 2, top - top % 2, width, height


def _fit_window(src_shape, src_aspect, fmt, geom):
    """Return the source window (x0, x1, y0, y1) in source pixels."""
    height, width = src_shape[:2]
    x0, x1, y0, y1 = 0.0, float(width), 0.0, float(height)
    if geom.fit == "cover":
        target = float(fmt.display_aspect)
        if float(src_aspect) > target:
            keep = width * target / float(src_aspect)
            x0, x1 = (width - keep) / 2.0, (width + keep) / 2.0
        else:
            keep = height * float(src_aspect) / target
            y0, y1 = (height - keep) / 2.0, (height + keep) / 2.0
    inset_x = (x1 - x0) * geom.overscan
    inset_y = (y1 - y0) * geom.overscan
    return x0 + inset_x, x1 - inset_x, y0 + inset_y, y1 - inset_y


class FieldWeaver:
    """Resample a stereo pair onto the interlaced field grid of a format.

    Both eyes share one destination rectangle but are sampled on the vertical
    grids of their own field, a quarter and three quarters of the way through
    each field line, so no vertical disparity is introduced by the weave.
    """

    def __init__(self, src_shape, src_aspect, fmt, geom=None, swap_eyes=False):
        self.fmt = fmt
        self.geom = geom or Geometry()
        self.swap_eyes = swap_eyes
        self.src_shape = tuple(src_shape[:2])
        self.src_aspect = Fraction(src_aspect).limit_denominator(10000)
        height, width = self.src_shape

        self.x, self.y, self.width, self.height = _fit_rect(
            self.src_aspect, fmt, self.geom.fit
        )
        x0, x1, y0, y1 = _fit_window(self.src_shape, self.src_aspect, fmt, self.geom)

        shift = 0.5 * self.geom.convergence * (x1 - x0) / self.width
        self._horizontal = []
        self._span = []
        for sign in (1.0, -1.0):
            window = (x0 + sign * shift, x1 + sign * shift)
            self._horizontal.append(
                resample_matrix(width, self.width, self.geom.kernel, 0.5, window)
            )
            self._span.append(source_span(width, self.width, 0.5, window))
        self._vertical = [
            resample_matrix(height, self.height // 2, self.geom.kernel, phase, (y0, y1))
            for phase in (0.25, 0.75)
        ]
        rows = self.height // 2
        self._vertical_first = rows * height * width + rows * width * self.width <= (
            self.width * width * height + rows * height * self.width
        )

    @property
    def field_shape(self):
        """Shape of one resampled eye picture."""
        return self.height // 2, self.width

    def eye_fields(self, left, right):
        """Return the (top, bottom) field pictures for a stereo pair."""
        eyes = (right, left) if self.swap_eyes else (left, right)
        out = []
        for index, eye in enumerate(eyes):
            source = np.asarray(eye, np.float32)
            if source.shape[:2] != self.src_shape:
                raise ValueError(
                    f"expected eye of shape {self.src_shape}, got {source.shape[:2]}"
                )
            picture = apply_matrix(
                apply_matrix(source, self._vertical[index], 0),
                self._horizontal[index],
                1,
            )
            lo, hi = self._span[index]
            if lo:
                picture[:, :lo] = self.geom.background
            if hi < self.width:
                picture[:, hi:] = self.geom.background
            out.append(np.rint(np.clip(picture, 0, 255)).astype(np.uint8))
        return out[0], out[1]

    def __call__(self, left, right):
        """Weave a stereo pair into one interlaced frame."""
        top, bottom = self.eye_fields(left, right)
        frame = np.empty((self.fmt.height, self.fmt.width, top.shape[2]), np.uint8)
        frame[:] = np.asarray(self.geom.background, np.uint8)
        rows = slice(self.y, self.y + self.height, 2)
        frame[rows, self.x : self.x + self.width] = top
        rows = slice(self.y + 1, self.y + self.height, 2)
        frame[rows, self.x : self.x + self.width] = bottom
        return frame
