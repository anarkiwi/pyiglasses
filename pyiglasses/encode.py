"""Encoding profiles that preserve field sequential stereo.

Two properties have to survive the encoder or the eyes are destroyed:

* the frame must be coded as interlaced with the top field first, so a player
  emits the left eye field first and the glasses route it to the left panel;
* nothing may resample vertically across the frame.  4:2:2 keeps chroma inside
  its own line and is the default; 4:2:0 shares one chroma line between two
  luma lines, which are different eyes, so 4:2:0 profiles carry a low level
  chroma cross talk that luma does not.  DVD-Video is 4:2:0 by specification.
"""

from dataclasses import dataclass, field
from fractions import Fraction

import av

from .color import to_video_frame
from .formats import FIELD_TT


@dataclass(frozen=True)
class EncodeProfile:
    """Codec, pixel format and muxer settings for one delivery target."""

    name: str
    codec: str
    pix_fmt: str
    container: str
    extension: str
    audio_codec: str | None = None
    audio_rate: int = 48000
    audio_bit_rate: int = 224000
    bit_rate: int = 0
    options: dict = field(default_factory=dict)
    muxer_options: dict = field(default_factory=dict)


PROFILES = {
    profile.name: profile
    for profile in (
        EncodeProfile(
            "mpeg2",
            "mpeg2video",
            "yuv422p",
            "matroska",
            ".mkv",
            audio_codec="flac",
            bit_rate=15_000_000,
            options={"maxrate": "20000k", "bufsize": "3000k"},
        ),
        EncodeProfile(
            "ffv1",
            "ffv1",
            "yuv422p",
            "matroska",
            ".mkv",
            audio_codec="flac",
            options={"level": "3", "coder": "1", "context": "1", "g": "1"},
        ),
        EncodeProfile(
            "dvd",
            "mpeg2video",
            "yuv420p",
            "dvd",
            ".mpg",
            audio_codec="mp2",
            bit_rate=6_000_000,
            options={"maxrate": "9000k", "bufsize": "1835008"},
            muxer_options={"muxrate": "10080000", "packetsize": "2048"},
        ),
        EncodeProfile(
            "h264",
            "libx264",
            "yuv422p",
            "mp4",
            ".mp4",
            audio_codec="aac",
            options={"crf": "18", "preset": "medium", "x264-params": "tff=1"},
        ),
    )
}

DEFAULT_PROFILE = "mpeg2"


def get_profile(name: str) -> EncodeProfile:
    """Look up an encoding profile by name."""
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"unknown profile {name!r}, want one of {sorted(PROFILES)}"
        ) from None


class InterlacedWriter:
    """Write RGB frames as an interlaced, top field first stereo stream."""

    def __init__(self, path, fmt, profile, audio_template=None):
        self.fmt = fmt
        self.profile = profile
        self.container = av.open(
            str(path),
            "w",
            format=profile.container or None,
            options=dict(profile.muxer_options),
        )
        stream = self.container.add_stream(
            profile.codec, rate=fmt.rate, options=dict(profile.options)
        )
        stream.width = fmt.width
        stream.height = fmt.height
        stream.pix_fmt = profile.pix_fmt
        stream.time_base = Fraction(1) / fmt.rate
        ctx = stream.codec_context
        stream.sample_aspect_ratio = fmt.sample_aspect
        ctx.sample_aspect_ratio = fmt.sample_aspect
        ctx.flags |= (
            av.codec.context.Flags.interlaced_dct | av.codec.context.Flags.interlaced_me
        )
        ctx.field_order = FIELD_TT
        ctx.gop_size = fmt.gop_size
        if profile.bit_rate:
            ctx.bit_rate = profile.bit_rate
        self.stream = stream
        self.time_base = stream.time_base
        self._graph, self._source, self._sink = self._build_graph()
        self._count = 0
        self.audio = (
            _AudioWriter(self.container, profile, audio_template)
            if audio_template
            else None
        )

    def _build_graph(self):
        graph = av.filter.Graph()
        source = graph.add_buffer(
            width=self.fmt.width,
            height=self.fmt.height,
            format=self.profile.pix_fmt,
            time_base=self.time_base,
        )
        params = graph.add("setparams", "field_mode=tff")
        sink = graph.add("buffersink")
        source.link_to(params)
        params.link_to(sink)
        graph.configure()
        return graph, source, sink

    def write(self, image):
        """Encode one woven RGB frame."""
        frame = to_video_frame(image, self.profile.pix_fmt)
        frame.pts = self._count
        frame.time_base = self.time_base
        self._count += 1
        self._source.push(frame)
        flagged = self._sink.pull()
        for packet in self.stream.encode(flagged):
            self.container.mux(packet)

    def write_audio(self, frame):
        """Encode one decoded audio frame, if audio is enabled."""
        if self.audio is not None:
            self.audio.write(frame)

    @property
    def frames_written(self):
        """Number of frames encoded so far."""
        return self._count

    def close(self):
        """Flush encoders and close the container."""
        for packet in self.stream.encode():
            self.container.mux(packet)
        if self.audio is not None:
            self.audio.close()
        self.container.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _AudioWriter:
    """Transcode the source audio into whatever the profile's container takes."""

    def __init__(self, container, profile, template):
        self.container = container
        rate = profile.audio_rate
        codec = av.codec.Codec(profile.audio_codec, "w")
        rates = tuple(codec.audio_rates or ())
        if rates and rate not in rates:
            rate = min(rates, key=lambda r: abs(r - rate))
        layout = "stereo" if len(template.layout.channels) > 1 else "mono"
        self.stream = container.add_stream(profile.audio_codec, rate=rate)
        self.stream.layout = layout
        if profile.audio_bit_rate and profile.audio_codec != "flac":
            self.stream.codec_context.bit_rate = profile.audio_bit_rate
        self.resampler = av.AudioResampler(
            format=self.stream.format,
            layout=layout,
            rate=rate,
            frame_size=self.stream.frame_size,
        )

    def write(self, frame):
        """Resample and encode one audio frame."""
        for resampled in self.resampler.resample(frame):
            for packet in self.stream.encode(resampled):
                self.container.mux(packet)

    def close(self):
        """Flush the resampler and the audio encoder."""
        for resampled in self.resampler.resample(None):
            for packet in self.stream.encode(resampled):
                self.container.mux(packet)
        for packet in self.stream.encode():
            self.container.mux(packet)
