"""Weaving a stereo pair onto the field grid."""

from fractions import Fraction

import numpy as np
import pytest

from pyiglasses.formats import get_format
from pyiglasses.resample import apply_matrix, resample_matrix
from pyiglasses.weave import FieldWeaver, Geometry

NTSC = get_format("ntsc")


def solid(height, width, colour):
    image = np.zeros((height, width, 3), np.uint8)
    image[:] = colour
    return image


def square(height, width, offset):
    image = np.zeros((height, width, 3), np.uint8)
    image[
        height // 3 : height // 2, width // 2 + offset - 8 : width // 2 + offset + 8
    ] = 255
    return image


def centroid(profile):
    profile = np.clip(profile - profile.max() * 0.5, 0, None)
    return float((profile * np.arange(len(profile))).sum() / profile.sum())


def test_left_eye_owns_the_even_lines():
    weaver = FieldWeaver((240, 320), Fraction(4, 3), NTSC)
    frame = weaver(solid(240, 320, (255, 0, 0)), solid(240, 320, (0, 0, 255)))
    assert frame.shape == (480, 720, 3)
    assert frame[0::2, :, 0].mean() > 200 and frame[0::2, :, 2].mean() < 10
    assert frame[1::2, :, 2].mean() > 200 and frame[1::2, :, 0].mean() < 10


def test_swap_eyes_puts_the_right_eye_first():
    weaver = FieldWeaver((240, 320), Fraction(4, 3), NTSC, swap_eyes=True)
    frame = weaver(solid(240, 320, (255, 0, 0)), solid(240, 320, (0, 0, 255)))
    assert frame[0::2, :, 2].mean() > 200


def test_fields_are_sampled_on_their_own_grid():
    """Weaving identical eyes must reproduce a plain resize of the source."""
    weaver = FieldWeaver((480, 320), Fraction(4, 3), NTSC, Geometry(fit="stretch"))
    ramp = np.repeat(np.linspace(0, 255, 480, dtype=np.float32)[:, None, None], 320, 1)
    ramp = np.repeat(ramp, 3, axis=2)
    top, bottom = weaver.eye_fields(ramp, ramp)
    expected_top = apply_matrix(ramp, resample_matrix(480, 240, phase=0.25), 0)
    expected_bottom = apply_matrix(ramp, resample_matrix(480, 240, phase=0.75), 0)
    assert np.abs(top[..., 0].mean(1) - expected_top[..., 0].mean(1)).max() < 1.5
    assert np.abs(bottom[..., 0].mean(1) - expected_bottom[..., 0].mean(1)).max() < 1.5
    assert bottom[..., 0].mean() > top[..., 0].mean(), "bottom field samples lower down"


def test_contain_letterboxes_a_wide_source():
    weaver = FieldWeaver(
        (270, 480), Fraction(16, 9), NTSC, Geometry(background=(9, 9, 9))
    )
    assert (weaver.x, weaver.width) == (0, 720)
    assert weaver.height < NTSC.height and weaver.y % 2 == 0
    frame = weaver(solid(270, 480, (255, 255, 255)), solid(270, 480, (255, 255, 255)))
    assert (frame[0] == 9).all(), "letterbox bars use the background colour"
    assert frame[NTSC.height // 2].mean() > 200


def test_cover_crops_instead_of_padding():
    weaver = FieldWeaver((270, 480), Fraction(16, 9), NTSC, Geometry(fit="cover"))
    assert (weaver.x, weaver.y, weaver.width, weaver.height) == (0, 0, 720, 480)
    frame = weaver(solid(270, 480, (255, 255, 255)), solid(270, 480, (255, 255, 255)))
    assert frame.min() > 200, "no background is left visible"


def test_stretch_fills_the_raster():
    weaver = FieldWeaver((270, 480), Fraction(16, 9), NTSC, Geometry(fit="stretch"))
    assert (weaver.width, weaver.height) == (720, 480)


def test_convergence_adds_the_requested_disparity():
    left, right = square(240, 320, 0), square(240, 320, -8)
    plain = FieldWeaver((240, 320), Fraction(4, 3), NTSC)
    shifted = FieldWeaver((240, 320), Fraction(4, 3), NTSC, Geometry(convergence=24))
    scale = 720 / 320
    for weaver, extra in ((plain, 0), (shifted, 24)):
        top, bottom = weaver.eye_fields(left, right)
        measured = centroid(bottom[..., 0].mean(0)) - centroid(top[..., 0].mean(0))
        assert measured == pytest.approx(-8 * scale + extra, abs=1.0)


def test_convergence_blanks_the_edge_it_shifts_off_the_source():
    """Positive convergence slides the left eye left, so its right edge runs out."""
    white = solid(240, 320, (255, 255, 255))
    top, bottom = FieldWeaver(
        (240, 320), Fraction(4, 3), NTSC, Geometry(convergence=40)
    ).eye_fields(white, white)
    assert top[:, -1].max() == 0 and top[:, 0].max() > 200
    assert bottom[:, 0].max() == 0 and bottom[:, -1].max() > 200


def test_overscan_zooms_in():
    marked = square(240, 320, 0)
    zoomed = FieldWeaver(
        (240, 320), Fraction(4, 3), NTSC, Geometry(overscan=0.1)
    ).eye_fields(marked, marked)[0]
    plain = FieldWeaver((240, 320), Fraction(4, 3), NTSC).eye_fields(marked, marked)[0]
    assert (zoomed[..., 0] > 128).sum() > 1.4 * (plain[..., 0] > 128).sum()


def test_mismatched_eye_shape_raises():
    weaver = FieldWeaver((240, 320), Fraction(4, 3), NTSC)
    with pytest.raises(ValueError, match="expected eye of shape"):
        weaver.eye_fields(solid(240, 320, 0), solid(120, 320, 0))


@pytest.mark.parametrize(
    "geometry", [{"fit": "squash"}, {"overscan": 0.9}, {"overscan": -0.1}]
)
def test_invalid_geometry_raises(geometry):
    with pytest.raises(ValueError):
        Geometry(**geometry)


def test_field_shape_matches_the_destination_rectangle():
    weaver = FieldWeaver((270, 480), Fraction(16, 9), NTSC)
    assert weaver.field_shape == (weaver.height // 2, weaver.width)
