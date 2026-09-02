"""Every profile has to come back interlaced and top field first."""

import av
import numpy as np
import pytest

from pyiglasses.encode import PROFILES, InterlacedWriter, get_profile
from pyiglasses.formats import FIELD_TT, get_format


def striped(fmt):
    frame = np.zeros((fmt.height, fmt.width, 3), np.uint8)
    frame[0::2, :, 0] = 220
    frame[1::2, :, 2] = 220
    return frame


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_profiles_preserve_the_fields(tmp_path, profile):
    fmt = get_format("ntsc")
    prof = get_profile(profile)
    path = tmp_path / f"out{prof.extension}"
    with InterlacedWriter(path, fmt, prof) as writer:
        for _ in range(6):
            writer.write(striped(fmt))
        assert writer.frames_written == 6

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        assert stream.codec_context.field_order == FIELD_TT
        assert (stream.codec_context.width, stream.codec_context.height) == (
            fmt.width,
            fmt.height,
        )
        decoded = [frame for frame in container.decode(stream)]
    assert decoded and all(frame.interlaced_frame for frame in decoded)
    image = decoded[0].to_ndarray(format="rgb24").astype(int)
    assert image[0::2, :, 0].mean() > 180 and image[1::2, :, 2].mean() > 180


@pytest.mark.parametrize("profile", ["ffv1", "dvd"])
def test_audio_is_transcoded_into_the_output(tmp_path, sbs_source, profile):
    prof = get_profile(profile)
    fmt = get_format("ntsc")
    with av.open(str(sbs_source)) as source:
        template = next(source.decode(source.streams.audio[0]))
        path = tmp_path / f"audio{prof.extension}"
        with InterlacedWriter(path, fmt, prof, template) as writer:
            writer.write(striped(fmt))
            for frame in source.decode(source.streams.audio[0]):
                writer.write_audio(frame)
    with av.open(str(path)) as container:
        assert container.streams.audio[0].codec_context.name == prof.audio_codec
        assert any(True for _ in container.decode(container.streams.audio[0]))


def test_writing_audio_without_a_source_is_a_no_op(tmp_path):
    fmt = get_format("ntsc")
    with InterlacedWriter(tmp_path / "silent.mkv", fmt, get_profile("ffv1")) as writer:
        writer.write_audio(None)
        writer.write(striped(fmt))


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="unknown profile"):
        get_profile("divx")
