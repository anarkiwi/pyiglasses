"""The resampling matrices are the arithmetic the whole encoder rests on."""

import numpy as np
import pytest

from pyiglasses.resample import (
    KERNELS,
    apply_matrix,
    resample_matrix,
    sample_centres,
    source_span,
)


def test_identity_when_scale_and_phase_are_neutral():
    matrix = resample_matrix(64, 64)
    assert np.allclose(matrix, np.eye(64), atol=1e-6)


@pytest.mark.parametrize("kernel", sorted(KERNELS))
@pytest.mark.parametrize(
    ("src", "dst", "phase"), [(100, 25, 0.25), (25, 100, 0.75), (7, 13, 0.5)]
)
def test_rows_sum_to_one(kernel, src, dst, phase):
    matrix = resample_matrix(src, dst, kernel=kernel, phase=phase)
    assert matrix.shape == (dst, src)
    assert np.allclose(matrix.sum(axis=1), 1.0, atol=1e-5)


def test_field_phases_are_exactly_one_frame_line_apart():
    """The invariant the whole field weave depends on."""
    height, field_height = 480, 120
    ramp = np.arange(height, dtype=np.float32)[:, None]
    top = apply_matrix(ramp, resample_matrix(height, field_height, phase=0.25), 0)
    bottom = apply_matrix(ramp, resample_matrix(height, field_height, phase=0.75), 0)
    expected = height / (2 * field_height)
    assert np.allclose((bottom - top)[5:-5], expected, atol=1e-3)


def test_downscaling_low_passes_rather_than_aliases():
    signal = np.tile(np.array([0.0, 255.0], np.float32), 128)[:, None]
    reduced = apply_matrix(signal, resample_matrix(256, 32), 0)
    assert np.ptp(reduced[2:-2]) < 8.0


def test_window_shifts_the_sampled_region():
    ramp = np.arange(100, dtype=np.float32)[:, None]
    shifted = apply_matrix(ramp, resample_matrix(100, 100, window=(10, 110)), 0)
    assert shifted[5, 0] == pytest.approx(15.0, abs=1e-3)


def test_apply_matrix_works_on_either_axis():
    image = np.arange(24, dtype=np.float32).reshape(4, 6)
    matrix = resample_matrix(6, 3, kernel="box")
    assert apply_matrix(image, matrix, 1).shape == (4, 3)
    assert apply_matrix(image.T, matrix, 0).shape == (3, 4)


def test_source_span_marks_samples_that_fall_off_the_source():
    assert source_span(100, 100) == (0, 100)
    assert source_span(100, 100, window=(-10, 90)) == (10, 100)
    assert source_span(100, 100, window=(10, 110)) == (0, 90)
    assert source_span(100, 100, window=(500, 600)) == (0, 0)


def test_sample_centres_follow_the_phase():
    centres, step = sample_centres(10, 5, phase=0.25)
    assert step == pytest.approx(2.0)
    assert centres[0] == pytest.approx(0.0)


def test_degenerate_kernel_still_normalises():
    matrix = resample_matrix(4, 8, kernel="box")
    assert np.allclose(matrix.sum(axis=1), 1.0)


@pytest.mark.parametrize(
    ("args", "kwargs"),
    [((0, 4), {}), ((4, 0), {}), ((4, 4), {"kernel": "sinc"})],
)
def test_bad_arguments_raise(args, kwargs):
    with pytest.raises(ValueError):
        resample_matrix(*args, **kwargs)
