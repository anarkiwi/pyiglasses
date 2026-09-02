"""Colour conversion must not average the two eyes together."""

import av
import numpy as np
import pytest

from pyiglasses.color import to_rgb, to_video_frame


def striped(height=480, width=720):
    """A frame whose fields are saturated in different, opposite hues."""
    frame = np.zeros((height, width, 3), np.uint8)
    frame[0::2, :, 0] = 200
    frame[1::2, :, 1] = 200
    return frame


@pytest.mark.parametrize("pix_fmt", ["yuv444p", "yuv422p", "yuv420p"])
def test_the_eyes_keep_their_own_colour(pix_fmt):
    frame = to_video_frame(striped(), pix_fmt)
    assert frame.format.name == pix_fmt
    out = to_rgb(frame).astype(int)
    assert out[0::2, :, 0].mean() > 170 and out[0::2, :, 1].mean() < 40
    assert out[1::2, :, 1].mean() > 170 and out[1::2, :, 0].mean() < 40


def test_generic_conversion_of_the_same_frame_loses_the_colour():
    """Why the field aware path exists at all."""
    plain = av.VideoFrame.from_ndarray(striped(), format="rgb24").reformat(
        format="yuv420p"
    )
    out = plain.to_ndarray(format="rgb24").astype(int)
    top = out[0::2]
    assert (
        abs(int(top[..., 0].mean()) - int(top[..., 1].mean())) < 40
    ), "eyes averaged to grey"


def test_field_subsampling_survives_a_round_trip_exactly_on_flat_colour():
    image = np.zeros((480, 720, 3), np.uint8)
    image[..., 2] = 180
    out = to_rgb(to_video_frame(image, "yuv420p")).astype(int)
    assert np.abs(out[..., 2] - 180).max() <= 3


def test_heights_that_cannot_carry_two_chroma_fields_are_rejected():
    with pytest.raises(ValueError, match="divisible by 4"):
        to_video_frame(np.zeros((6, 8, 3), np.uint8), "yuv420p")


def test_non_planar_targets_fall_through_to_swscale():
    frame = to_video_frame(striped(8, 8), "rgb24")
    assert frame.format.name == "rgb24"
    assert to_rgb(frame).shape == (8, 8, 3)
