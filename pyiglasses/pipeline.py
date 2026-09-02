"""Decode a stereo source, weave it into fields, and encode it for the glasses."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np

from .encode import DEFAULT_PROFILE, InterlacedWriter, get_profile
from .formats import DEFAULT_FORMAT, VideoFormat, get_format
from .stereo import DEFAULT_LAYOUT, deduce_eye_aspect, get_layout
from .weave import FieldWeaver, Geometry


class VideoSource:
    """Decoded RGB frames from one input, sampled on an arbitrary output clock.

    Source and output frame rates rarely match, so frames are held and repeated
    or dropped against the output clock.  Each input is sampled independently,
    which keeps two separately shot eyes in step even at different rates.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.container = av.open(str(path))
        self.stream = self.container.streams.video[0]
        self.stream.thread_type = "AUTO"
        self._frames = self.container.decode(self.stream)
        self._index = 0
        self._origin = None
        self._current = self._pull()
        self._next = self._pull()

    def _pull(self):
        for frame in self._frames:
            time = frame.time
            if time is None:
                time = float(self._index / self.rate)
            if self._origin is None:
                self._origin = time
            self._index += 1
            return time - self._origin, frame.to_ndarray(format="rgb24")
        return None

    @property
    def rate(self):
        """Average source frame rate."""
        return self.stream.average_rate or self.stream.guessed_rate or Fraction(25)

    @property
    def size(self):
        """(height, width) of a decoded frame."""
        return self.stream.codec_context.height, self.stream.codec_context.width

    @property
    def sample_aspect(self):
        """Source pixel aspect ratio, defaulting to square."""
        return Fraction(self.stream.sample_aspect_ratio or 1)

    @property
    def duration(self):
        """Source duration in seconds, or None if unknown."""
        if self.stream.duration is not None:
            return float(self.stream.duration * self.stream.time_base)
        if self.container.duration is not None:
            return self.container.duration / av.time_base
        return None

    def at(self, time):
        """Return the frame covering ``time`` seconds, or None past the end.

        The last frame covers one source frame period, after which the source
        is done and the output stops.
        """
        while self._next is not None and self._next[0] <= time:
            self._current, self._next = self._next, self._pull()
        if self._current is None:
            return None
        if self._next is None and time > self._current[0] + float(1 / self.rate):
            return None
        return self._current[1]

    def close(self):
        """Close the underlying container."""
        self.container.close()


class AudioSource:
    """Audio frames from an input, pumped in step with the video clock."""

    def __init__(self, path):
        self.container = av.open(str(path))
        streams = self.container.streams.audio
        self.stream = streams[0] if streams else None
        self._frames = self.container.decode(self.stream) if self.stream else iter(())
        self._pending = next(self._frames, None)

    @property
    def template(self):
        """A decoded frame describing the source layout, or None."""
        return self._pending

    def until(self, time):
        """Yield decoded audio frames up to ``time`` seconds."""
        while self._pending is not None:
            when = self._pending.time
            if when is not None and when > time:
                return
            yield self._pending
            self._pending = next(self._frames, None)

    def close(self):
        """Close the underlying container."""
        self.container.close()


@dataclass
class EncodeResult:
    """What an encode produced."""

    path: Path
    frames: int
    video_format: VideoFormat
    profile: str
    eye_size: tuple
    eye_aspect: Fraction
    rect: tuple

    @property
    def duration(self):
        """Encoded duration in seconds."""
        return float(self.frames / self.video_format.rate)


def encode_stereo(
    source,
    output,
    right_source=None,
    layout=DEFAULT_LAYOUT,
    video_format=DEFAULT_FORMAT,
    profile=DEFAULT_PROFILE,
    geometry=None,
    swap_eyes=False,
    eye_aspect=None,
    audio=True,
    max_frames=None,
    progress=None,
):
    """Encode a stereo source as field sequential 3D for the i-glasses!.

    ``source`` is a packed side by side or over under file, or the left eye when
    ``right_source`` is given (``layout='separate'``).
    """
    fmt = get_format(video_format) if isinstance(video_format, str) else video_format
    prof = get_profile(profile) if isinstance(profile, str) else profile
    lay = get_layout(layout)
    if (lay.axis is None) != (right_source is not None):
        raise ValueError("layout 'separate' needs two inputs; packed layouts take one")

    sources = [VideoSource(source)] + (
        [VideoSource(right_source)] if right_source else []
    )
    audio_source = AudioSource(source) if audio else None
    try:
        height, width = sources[0].size
        eye_size = lay.eye_shape(height, width)
        aspect = (
            Fraction(eye_aspect)
            if eye_aspect
            else deduce_eye_aspect(*eye_size, sources[0].sample_aspect, lay)
        )
        weaver = FieldWeaver(eye_size, aspect, fmt, geometry or Geometry(), swap_eyes)
        template = audio_source.template if audio_source else None
        with InterlacedWriter(output, fmt, prof, template) as writer:
            for index in _encode_frames(
                sources, lay, weaver, writer, fmt, max_frames, progress
            ):
                if audio_source is not None:
                    for frame in audio_source.until(float((index + 1) / fmt.rate)):
                        writer.write_audio(frame)
            frames = writer.frames_written
    finally:
        for src in sources:
            src.close()
        if audio_source is not None:
            audio_source.close()

    return EncodeResult(
        path=Path(output),
        frames=frames,
        video_format=fmt,
        profile=prof.name,
        eye_size=eye_size,
        eye_aspect=aspect,
        rect=(weaver.x, weaver.y, weaver.width, weaver.height),
    )


def _encode_frames(sources, layout, weaver, writer, fmt, max_frames, progress):
    """Drive the output clock, weaving and encoding one frame per tick."""
    index = 0
    while max_frames is None or index < max_frames:
        time = float(index / fmt.rate)
        frames = [src.at(time) for src in sources]
        if any(frame is None for frame in frames):
            return
        if layout.axis is None:
            left, right = frames
        else:
            left, right = layout.split(np.asarray(frames[0]))
        writer.write(weaver(left, right))
        if progress is not None:
            progress(index)
        yield index
        index += 1
