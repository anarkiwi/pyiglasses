"""Stereo packing layouts."""

from fractions import Fraction

import numpy as np
import pytest

from pyiglasses.stereo import deduce_eye_aspect, get_layout


def test_side_by_side_splits_horizontally():
    frame = np.arange(24).reshape(4, 6)
    left, right = get_layout("sbs").split(frame)
    assert left.shape == right.shape == (4, 3)
    assert list(left[0]) == [0, 1, 2] and list(right[0]) == [3, 4, 5]


def test_over_under_splits_vertically():
    frame = np.arange(24).reshape(4, 6)
    left, right = get_layout("ou").split(frame)
    assert left.shape == right.shape == (2, 6)
    assert list(left[0]) == [0, 1, 2, 3, 4, 5]


def test_odd_sizes_drop_the_spare_line():
    left, right = get_layout("ou").split(np.zeros((5, 6)))
    assert left.shape == right.shape == (2, 6)


def test_separate_layout_cannot_split():
    with pytest.raises(ValueError, match="two separate inputs"):
        get_layout("separate").split(np.zeros((4, 4)))
    assert get_layout("separate").eye_shape(4, 6) == (4, 6)


@pytest.mark.parametrize(
    ("width", "height", "layout"),
    [(1920, 1080, "sbs"), (3840, 1080, "sbs"), (1920, 1080, "ou"), (1920, 2160, "ou")],
)
def test_common_packings_all_resolve_to_the_authored_aspect(width, height, layout):
    lay = get_layout(layout)
    assert deduce_eye_aspect(
        *lay.eye_shape(height, width), Fraction(1), lay
    ) == Fraction(16, 9)


def test_anamorphic_pixels_are_taken_into_account():
    lay = get_layout("sbs")
    assert deduce_eye_aspect(576, 720, Fraction(16, 15), lay) == Fraction(4, 3)


def test_unknown_layout_raises():
    with pytest.raises(ValueError, match="unknown layout"):
        get_layout("anaglyph")
