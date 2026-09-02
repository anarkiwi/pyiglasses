"""End to end: a stereo source in, a field sequential file out."""

import av
import numpy as np
import pytest

from pyiglasses.color import to_rgb
from pyiglasses.pipeline import VideoSource, encode_stereo
from pyiglasses.weave import Geometry


def field_centroid(image, channel):
    profile = image[..., channel].mean(0)
    profile = np.clip(profile - profile.max() * 0.5, 0, None)
    return float((profile * np.arange(len(profile))).sum() / profile.sum())


def first_frame(path):
    with av.open(str(path)) as container:
        for frame in container.decode(video=0):
            return to_rgb(frame).astype(float)
    raise AssertionError("no frames")


def test_packed_source_becomes_field_sequential(tmp_path, sbs_source, disparity):
    result = encode_stereo(sbs_source, tmp_path / "out.mkv", profile="ffv1")
    assert result.frames == pytest.approx(6 / 24 * 30000 / 1001, abs=1)
    assert result.duration > 0.2
    assert result.eye_size == (240, 160)
    image = first_frame(result.path)
    top, bottom = image[0::2], image[1::2]
    measured = field_centroid(bottom, 2) - field_centroid(top, 0)
    assert measured == pytest.approx(-disparity * result.rect[2] / 160, abs=2.0)


def test_frame_rate_is_conformed_to_the_output_clock(tmp_path, sbs_source):
    """Six frames of 24 fps material fill a quarter second of 29.97 fps output."""
    result = encode_stereo(
        sbs_source, tmp_path / "pal.mkv", video_format="pal", profile="ffv1"
    )
    assert result.frames == pytest.approx(6 / 24 * 25, abs=1)
    assert result.video_format.name == "pal"


def test_separate_eyes_are_encoded_together(tmp_path, eye_sources, disparity):
    left, right = eye_sources
    result = encode_stereo(
        left,
        tmp_path / "sep.mkv",
        right_source=right,
        layout="separate",
        profile="ffv1",
    )
    assert result.frames == pytest.approx(6, abs=1)
    image = first_frame(result.path)
    measured = field_centroid(image[1::2], 2) - field_centroid(image[0::2], 0)
    assert measured == pytest.approx(-disparity * result.rect[2] / 320, abs=2.0)


def test_convergence_moves_the_scene(tmp_path, eye_sources, disparity):
    left, right = eye_sources
    shift = 20
    result = encode_stereo(
        left,
        tmp_path / "conv.mkv",
        right_source=right,
        layout="separate",
        profile="ffv1",
        geometry=Geometry(convergence=shift),
    )
    image = first_frame(result.path)
    measured = field_centroid(image[1::2], 2) - field_centroid(image[0::2], 0)
    assert measured == pytest.approx(-disparity * result.rect[2] / 320 + shift, abs=2.0)


def test_audio_is_carried_through(tmp_path, sbs_source):
    result = encode_stereo(sbs_source, tmp_path / "sound.mkv", profile="ffv1")
    with av.open(str(result.path)) as container:
        assert container.streams.audio


def test_audio_can_be_dropped(tmp_path, sbs_source):
    result = encode_stereo(
        sbs_source, tmp_path / "quiet.mkv", profile="ffv1", audio=False
    )
    with av.open(str(result.path)) as container:
        assert not container.streams.audio


def test_max_frames_stops_early(tmp_path, sbs_source):
    result = encode_stereo(
        sbs_source, tmp_path / "short.mkv", profile="ffv1", max_frames=3
    )
    assert result.frames == 3


def test_progress_is_reported(tmp_path, sbs_source):
    seen = []
    encode_stereo(
        sbs_source,
        tmp_path / "p.mkv",
        profile="ffv1",
        max_frames=2,
        progress=seen.append,
    )
    assert seen == [0, 1]


def test_over_under_layout(tmp_path, sbs_source):
    result = encode_stereo(sbs_source, tmp_path / "ou.mkv", layout="ou", profile="ffv1")
    assert result.eye_size == (120, 320)


def test_explicit_eye_aspect_overrides_deduction(tmp_path, sbs_source):
    result = encode_stereo(
        sbs_source, tmp_path / "a.mkv", profile="ffv1", eye_aspect="1/1", max_frames=1
    )
    assert result.eye_aspect == 1
    assert result.rect[2] < result.video_format.width, "a square picture is pillarboxed"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"layout": "separate"}, "two inputs"),
        ({"right_source": "unused.mkv"}, "packed layouts take one"),
    ],
)
def test_layout_and_input_count_must_agree(tmp_path, sbs_source, kwargs, message):
    with pytest.raises(ValueError, match=message):
        encode_stereo(sbs_source, tmp_path / "bad.mkv", **kwargs)


def test_source_holds_the_last_frame_for_one_period_then_ends(sbs_source):
    source = VideoSource(sbs_source)
    assert source.at(0.0) is not None
    assert source.duration is None or source.duration > 0
    assert source.at(10.0) is None
    source.close()
