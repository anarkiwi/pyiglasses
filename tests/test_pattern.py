"""The test pattern and the font it is labelled with."""

import numpy as np
import pytest

from pyiglasses import font
from pyiglasses.formats import get_format
from pyiglasses.pattern import frame


@pytest.mark.parametrize("name", ["ntsc", "pal"])
def test_pattern_fills_the_raster_with_two_different_fields(name):
    fmt = get_format(name)
    image = frame(fmt)
    assert image.shape == (fmt.height, fmt.width, 3)
    assert np.abs(image[0::2].astype(int) - image[1::2]).mean() > 1.0


def test_swapping_exchanges_the_fields():
    fmt = get_format("ntsc")
    plain, swapped = frame(fmt), frame(fmt, swap_eyes=True)
    assert (plain[0::2] == swapped[1::2]).all()
    assert (plain[1::2] == swapped[0::2]).all()


def test_the_comb_alternates_every_field_line():
    """A vertical filter anywhere in the chain flattens this."""
    image = frame(get_format("ntsc"))
    top = image[0::2]
    rows = top.mean(axis=(1, 2))
    assert np.abs(np.diff(rows)).max() > 30


def test_font_renders_and_measures():
    mask = font.render("3D")
    assert mask.shape == (7, 12)
    assert mask.any()
    assert font.text_size("3D", 2) == (14, 24)


def test_font_draws_into_an_image_and_clips_at_the_edge():
    image = np.zeros((10, 10, 3), np.uint8)
    font.draw(image, "L", 6, 6, 1, (255, 0, 0))
    assert image[..., 0].any()
    font.draw(image, "L", 20, 20)
    assert not image[..., 1].any()


def test_unknown_glyphs_are_an_error():
    with pytest.raises(ValueError, match="no glyph"):
        font.render("hello!")
