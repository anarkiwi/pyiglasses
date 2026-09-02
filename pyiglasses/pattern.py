"""A stereo test pattern for bringing up i-glasses! hardware.

The pattern is authored directly on the field grid, one field per eye, so it is
pixel exact: the single field line features it uses are the ones that reveal a
player or a capture path that has quietly deinterlaced or line averaged the
signal.  It answers the questions that come up first on real hardware: are the
eyes separated at all, are they the right way round, how much parallax is
comfortable, and is the geometry right.
"""

import numpy as np

from . import font

WHITE = (255, 255, 255)
GREY = (128, 128, 128)
LEFT_COLOUR = (255, 96, 96)
RIGHT_COLOUR = (96, 160, 255)
# Disparity in output pixels; positive is uncrossed and sits behind the screen.
DISPARITIES = (-24, -16, -8, 0, 8, 16, 24)


def _box(field, x0, y0, x1, y1, colour, thickness=1):
    field[y0 : y0 + thickness, x0:x1] = colour
    field[y1 - thickness : y1, x0:x1] = colour
    field[y0:y1, x0 : x0 + thickness] = colour
    field[y0:y1, x1 - thickness : x1] = colour


def _ellipse(field, cx, cy, rx, ry, colour, thickness=1.5):
    ys, xs = np.ogrid[: field.shape[0], : field.shape[1]]
    radius = np.hypot((xs - cx) / rx, (ys - cy) / ry)
    field[np.abs(radius - 1.0) < thickness / max(rx, ry)] = colour


def _eye_field(fmt, eye, label, colour):
    """Draw one eye's field picture."""
    width, height = fmt.width, fmt.field_height
    margin_x, margin_y = width // 40, height // 24
    field = np.zeros((height, width, 3), np.uint8)
    label_scale = max(2, height // 60)
    small = max(1, height // 120)

    _box(field, 0, 0, width, height, GREY)
    _box(field, margin_x, margin_y, width - margin_x, height - margin_y, (72, 72, 72))

    steps = 8
    for index in range(steps):
        level = index * 255 // (steps - 1)
        x0 = margin_x + index * (width - 2 * margin_x) // steps
        x1 = margin_x + (index + 1) * (width - 2 * margin_x) // steps
        field[int(height * 0.07) : int(height * 0.13), x0:x1] = (level, level, level)

    text_width = font.text_size(label, label_scale)[1]
    font.draw(
        field, label, (width - text_width) // 2, int(height * 0.17), label_scale, colour
    )

    # A field line is twice as deep in the frame as it is tall, so the circle is
    # squeezed by the pixel aspect and by the field decimation to read as round.
    aspect = float(fmt.sample_aspect) / 2.0
    centre_y = int(height * 0.45)
    radius_y = int(height * 0.15)
    _ellipse(field, width // 2, centre_y, radius_y / aspect, radius_y, WHITE)
    field[centre_y, width // 2 - 16 : width // 2 + 16] = WHITE
    field[centre_y - 8 : centre_y + 8, width // 2] = WHITE

    # Parallax ruler: each target is split by its disparity, sign flipped per eye.
    ruler_y = int(height * 0.66)
    sign = -1 if eye == 0 else 1
    step = width // (len(DISPARITIES) + 1)
    for index, disparity in enumerate(DISPARITIES):
        centre = step * (index + 1) + sign * disparity // 2
        field[
            ruler_y : ruler_y + small * 6, centre - small * 3 : centre + small * 3
        ] = WHITE
        text = f"{disparity:+d}"
        font.draw(
            field,
            text,
            centre - font.text_size(text, small)[1] // 2,
            ruler_y + small * 8,
            small,
            WHITE,
        )

    # One eye sees the block, the other sees the comb: proof that the two fields
    # reach different panels, and that nothing has filtered vertically on the way.
    band_y = int(height * 0.84)
    band_h = small * 12
    text = "left only" if eye == 0 else "right only"
    block_w = font.text_size(text, small)[1] + small * 8
    block_x = margin_x * 2 if eye == 0 else width - margin_x * 2 - block_w
    field[band_y : band_y + band_h, block_x : block_x + block_w] = colour
    font.draw(field, text, block_x + small * 4, band_y + small * 2, small, (0, 0, 0))

    comb_w = width // 5
    comb_x = width - margin_x * 2 - comb_w if eye == 0 else margin_x * 2
    comb = field[band_y : band_y + band_h, comb_x : comb_x + comb_w]
    comb[0::2] = WHITE
    comb[1::2] = 0
    return field


def frame(fmt, swap_eyes=False):
    """Return one woven interlaced test pattern frame."""
    fields = [
        _eye_field(fmt, 0, "left", LEFT_COLOUR),
        _eye_field(fmt, 1, "right", RIGHT_COLOUR),
    ]
    if swap_eyes:
        fields.reverse()
    out = np.empty((fmt.height, fmt.width, 3), np.uint8)
    out[0::2] = fields[0]
    out[1::2] = fields[1]
    return out
