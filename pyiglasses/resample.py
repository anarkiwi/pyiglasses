"""Separable polyphase resampling with an explicit output sample phase.

Field sequential 3D puts the left eye on frame lines 0, 2, 4 ... and the right
eye on lines 1, 3, 5 ...  The two eyes are therefore sampled on grids that are
one frame line apart, so each eye needs its own vertical resampling phase.
Scaling both eyes to the field height with an ordinary resizer and weaving the
result gives the right eye one frame line of spurious vertical disparity.

A resampling is built once as a dense (dst, src) matrix and applied with a BLAS
matrix multiply per axis, which is faster than any per-pixel Python or numba
loop and keeps the per-frame work to two matmuls.
"""

import numpy as np


def _lanczos3(x):
    return np.where(np.abs(x) < 3.0, np.sinc(x) * np.sinc(x / 3.0), 0.0)


def _catrom(x):
    x = np.abs(x)
    x2 = x * x
    return np.where(
        x < 1.0,
        1.5 * x2 * x - 2.5 * x2 + 1.0,
        np.where(x < 2.0, -0.5 * x2 * x + 2.5 * x2 - 4.0 * x + 2.0, 0.0),
    )


def _triangle(x):
    return np.clip(1.0 - np.abs(x), 0.0, None)


def _box(x):
    return (np.abs(x) <= 0.5).astype(np.float64)


KERNELS = {
    "lanczos": (_lanczos3, 3.0),
    "catrom": (_catrom, 2.0),
    "triangle": (_triangle, 1.0),
    "box": (_box, 0.5),
}


def sample_centres(src_n, dst_n, phase=0.5, window=None):
    """Return the source pixel index of each output sample, and the step."""
    start, stop = (
        (0.0, float(src_n)) if window is None else (float(window[0]), float(window[1]))
    )
    step = (stop - start) / dst_n
    return start + (np.arange(dst_n) + phase) * step - 0.5, step


def resample_matrix(src_n, dst_n, kernel="lanczos", phase=0.5, window=None):
    """Return a (dst_n, src_n) float32 resampling matrix.

    Output sample ``i`` is centred at ``start + (i + phase) * (stop - start) /
    dst_n`` in source pixel units, where ``window`` defaults to the whole source.
    ``phase`` is 0.5 for an ordinary centred resize; a field of an interlaced
    frame uses 0.25 (top) or 0.75 (bottom).  The kernel is widened when
    downscaling so it low passes rather than aliases, and the source is edge
    replicated.
    """
    if src_n < 1 or dst_n < 1:
        raise ValueError("resample needs at least one sample per axis")
    try:
        func, radius = KERNELS[kernel]
    except KeyError:
        raise ValueError(
            f"unknown kernel {kernel!r}, want one of {sorted(KERNELS)}"
        ) from None

    centres, step = sample_centres(src_n, dst_n, phase, window)
    support = radius * max(1.0, abs(step))

    taps = int(np.ceil(2.0 * support)) + 1
    first = np.ceil(centres - support).astype(np.int64)
    idx = first[:, None] + np.arange(taps)[None, :]
    weights = func((idx - centres[:, None]) / max(1.0, abs(step)))
    total = weights.sum(axis=1, keepdims=True)
    degenerate = total[:, 0] == 0.0
    if degenerate.any():
        weights[degenerate] = np.abs(idx[degenerate] - centres[degenerate, None]) < 0.5
        total = weights.sum(axis=1, keepdims=True)
    weights /= total

    matrix = np.zeros((dst_n, src_n), np.float64)
    rows = np.repeat(np.arange(dst_n), taps)
    np.add.at(matrix, (rows, np.clip(idx, 0, src_n - 1).ravel()), weights.ravel())
    return matrix.astype(np.float32)


def apply_matrix(image, matrix, axis):
    """Resample ``image`` along ``axis`` with a (dst, src) matrix."""
    moved = np.moveaxis(image, axis, 0)
    out = np.tensordot(matrix, moved, axes=1)
    return np.moveaxis(out, 0, axis)


def source_span(src_n, dst_n, phase=0.5, window=None):
    """Return the output index range whose samples sit inside the source image.

    Edge replication is invisible for an unshifted resize but smears when the
    window is shifted off the source, as convergence adjustment does; callers
    use this span to blank the outputs that have no real source behind them.
    """
    centres, _ = sample_centres(src_n, dst_n, phase, window)
    inside = (centres >= -0.5) & (centres <= src_n - 0.5)
    if not inside.any():
        return 0, 0
    return int(np.argmax(inside)), int(dst_n - np.argmax(inside[::-1]))
