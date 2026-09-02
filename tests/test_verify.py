"""Verification catches the silent ways a file stops being 3D."""

import pytest

from pyiglasses.formats import get_format
from pyiglasses.pipeline import encode_stereo
from pyiglasses.verify import verify


def test_a_good_encode_passes(tmp_path, sbs_source, disparity):
    result = encode_stereo(sbs_source, tmp_path / "good.mkv", profile="mpeg2")
    report = verify(result.path)
    assert report.ok, report.issues
    assert report.matched_format == "ntsc"
    assert report.interlaced_frames == report.frames > 0
    assert report.field_difference > 1.0
    expected = -disparity * result.rect[2] / 160
    assert report.disparity == pytest.approx(expected, abs=4)
    assert any("separation" in line for line in report.lines())


def test_a_two_dimensional_source_is_rejected(tmp_path, flat_source):
    result = encode_stereo(
        flat_source, tmp_path / "flat.mkv", profile="ffv1", audio=False
    )
    report = verify(result.path)
    assert not report.ok
    assert any("no stereo" in issue for issue in report.issues)


def test_a_progressive_input_fails_every_structural_check(sbs_source):
    report = verify(sbs_source)
    assert not report.ok
    joined = " ".join(report.issues)
    assert "top field first" in joined
    assert "not flagged interlaced" in joined
    assert "no i-glasses" in joined


def test_four_two_zero_is_noted_but_not_an_error(tmp_path, sbs_source):
    result = encode_stereo(sbs_source, tmp_path / "dvd.mpg", profile="dvd")
    report = verify(result.path)
    assert report.ok
    assert any("4:2:0" in note for note in report.warnings)


def test_unsignalled_pixel_aspect_is_noted(tmp_path, sbs_source):
    result = encode_stereo(sbs_source, tmp_path / "lossless.mkv", profile="ffv1")
    report = verify(result.path, video_format=get_format("ntsc"))
    assert any("pixel aspect" in note for note in report.warnings)


def test_a_file_with_no_video_frames_reports_so(tmp_path, sbs_source):
    report = verify(sbs_source, max_frames=0)
    assert not report.ok
    assert report.issues == ["no video frames decoded"]
