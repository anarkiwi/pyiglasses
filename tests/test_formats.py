"""Video format tables."""

from fractions import Fraction

import pytest

from pyiglasses.formats import FORMATS, get_format


@pytest.mark.parametrize("name", sorted(FORMATS))
def test_every_format_is_a_valid_interlaced_raster(name):
    fmt = get_format(name)
    assert fmt.height % 4 == 0, "field aware chroma needs a height divisible by four"
    assert fmt.field_height * 2 == fmt.height
    assert fmt.field_rate == fmt.rate * 2
    assert fmt.display_aspect == Fraction(4, 3)


def test_unknown_format_raises():
    with pytest.raises(ValueError, match="unknown format"):
        get_format("vga")
