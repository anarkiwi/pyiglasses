"""Check that an encoded file is really field sequential 3D.

The failure modes are silent: a file that decodes and looks fine as 2D can have
progressive framing, the wrong field order, or two identical fields, and the
only symptom is that the glasses show a flat or eye swapped picture.
"""

from dataclasses import dataclass, field
from fractions import Fraction

import av
import numpy as np

from .color import to_rgb
from .formats import FIELD_TT, FORMATS

# Disparity search range, as a fraction of the raster width.
DISPARITY_SEARCH = 8


@dataclass
class VerifyReport:
    """What a file claims to be, and what its fields actually contain."""

    path: str
    codec: str = ""
    pix_fmt: str = ""
    width: int = 0
    height: int = 0
    rate: Fraction = Fraction(0)
    sample_aspect: Fraction = Fraction(1)
    field_order: int = 0
    frames: int = 0
    interlaced_frames: int = 0
    field_difference: float = 0.0
    disparity: int = 0
    matched_format: str = ""
    issues: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        """True when nothing would stop the glasses seeing 3D."""
        return not self.issues

    def lines(self):
        """Render the report as text lines."""
        out = [
            f"{self.path}",
            f"  codec        {self.codec} {self.pix_fmt} {self.width}x{self.height}",
            f"  rate         {float(self.rate):.3f} fps, sar {self.sample_aspect}",
            f"  format       {self.matched_format or 'non standard'}",
            f"  interlaced   {self.interlaced_frames}/{self.frames} frames,"
            f" field order {'top first' if self.field_order == FIELD_TT else self.field_order}",
            f"  separation   {self.field_difference:.2f}/255 mean field difference,"
            f" {self.disparity:+d} px dominant disparity",
        ]
        out += [f"  ISSUE        {issue}" for issue in self.issues]
        out += [f"  note         {note}" for note in self.warnings]
        if self.ok:
            out.append("  OK")
        return out


def _dominant_disparity(top, bottom, limit=None):
    """Estimate the horizontal shift between the eyes by minimising abs error."""
    luma = [image[..., :3].mean(axis=2)[::4, ::2] for image in (top, bottom)]
    inset = max(1, (limit or top.shape[1] // DISPARITY_SEARCH) // 2)
    reference = luma[0][:, inset:-inset]
    best, score = 0, None
    for shift in range(-inset, inset + 1):
        window = luma[1][:, inset + shift : luma[1].shape[1] - inset + shift]
        error = float(np.abs(window - reference).mean())
        if score is None or error < score:
            best, score = shift, error
    return best * 2


def verify(path, video_format=None, max_frames=32):
    """Inspect an encoded file and report anything that breaks stereo."""
    report = VerifyReport(path=str(path))
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        ctx = stream.codec_context
        report.codec = ctx.name
        report.width, report.height = ctx.width, ctx.height
        report.rate = stream.average_rate or Fraction(0)
        report.sample_aspect = Fraction(stream.sample_aspect_ratio or 1)
        report.field_order = ctx.field_order
        differences, disparities = [], []
        for frame in container.decode(stream):
            if report.frames >= max_frames:
                break
            report.frames += 1
            report.pix_fmt = frame.format.name
            report.interlaced_frames += bool(frame.interlaced_frame)
            image = to_rgb(frame).astype(np.float32)
            top, bottom = image[0::2], image[1::2]
            differences.append(float(np.abs(top - bottom).mean()))
            disparities.append(_dominant_disparity(top, bottom))
    if not report.frames:
        report.issues.append("no video frames decoded")
        return report
    report.field_difference = float(np.mean(differences))
    report.disparity = int(np.median(disparities))
    limit = report.width // DISPARITY_SEARCH

    expected = video_format or _match_format(report)
    report.matched_format = expected.name if expected else ""
    if report.field_order != FIELD_TT:
        report.issues.append(
            "field order is not top field first: the eyes will be swapped"
        )
    if report.interlaced_frames < report.frames:
        missing = report.frames - report.interlaced_frames
        report.issues.append(f"{missing} frames are not flagged interlaced")
    if report.height % 2:
        report.issues.append("odd frame height cannot carry two fields")
    if abs(report.disparity) >= limit - 1:
        report.warnings.append(
            f"disparity is at the {limit} px search limit: the real offset may be larger"
        )
    if report.field_difference < 1.0:
        report.issues.append(
            "the fields are near identical: this file carries no stereo"
        )
    if expected is None:
        report.issues.append("frame size and rate match no i-glasses! video format")
    elif report.sample_aspect != expected.sample_aspect:
        report.warnings.append(
            f"pixel aspect is signalled as {report.sample_aspect}, {expected.name} is"
            f" {expected.sample_aspect}; software players will show the wrong shape"
        )
    if report.pix_fmt.endswith("420p"):
        report.warnings.append(
            "4:2:0 shares chroma between fields unless the decoder is field aware;"
            " prefer a 4:2:2 profile where the target allows it"
        )
    return report


def _match_format(report):
    """Return the video format a report's geometry and rate correspond to."""
    for fmt in FORMATS.values():
        if (fmt.width, fmt.height) == (report.width, report.height) and abs(
            float(fmt.rate) - float(report.rate)
        ) < 0.01:
            return fmt
    return None
