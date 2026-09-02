"""Command line surface."""

import av
import pytest

from pyiglasses.cli import main


def test_formats_lists_everything(capsys):
    assert main(["formats"]) == 0
    out = capsys.readouterr().out
    assert "ntsc" in out and "mpeg2" in out and "sbs" in out


def test_encode_reports_the_geometry_it_chose(tmp_path, sbs_source, capsys):
    output = tmp_path / "out.mkv"
    assert main(["encode", str(sbs_source), "-o", str(output), "-p", "ffv1"]) == 0
    assert "eye 160x240" in capsys.readouterr().out
    assert output.exists()


def test_encode_with_two_eyes_selects_the_separate_layout(
    tmp_path, eye_sources, capsys
):
    left, right = eye_sources
    output = tmp_path / "sep.mkv"
    argv = ["encode", str(left), "--right", str(right), "-o", str(output), "-p", "ffv1"]
    assert main(argv) == 0
    assert output.exists()
    assert "ntsc ffv1" in capsys.readouterr().out


def test_encode_passes_the_geometry_options_through(tmp_path, sbs_source):
    output = tmp_path / "geom.mkv"
    argv = [
        "encode",
        str(sbs_source),
        "-o",
        str(output),
        "-p",
        "ffv1",
        "--fit",
        "cover",
        "--overscan",
        "0.05",
        "--convergence",
        "8",
        "--kernel",
        "catrom",
        "--eye-aspect",
        "16:9",
        "--swap-eyes",
        "--no-audio",
        "--frames",
        "2",
    ]
    assert main(argv) == 0
    with av.open(str(output)) as container:
        assert not container.streams.audio


def test_pattern_writes_a_playable_file(tmp_path, capsys):
    output = tmp_path / "pattern.mkv"
    assert main(["pattern", "-o", str(output), "-d", "0.2", "-p", "ffv1"]) == 0
    assert "test pattern" in capsys.readouterr().out
    with av.open(str(output)) as container:
        assert container.streams.video[0].codec_context.height == 480


def test_verify_exit_code_follows_the_report(tmp_path, sbs_source, capsys):
    output = tmp_path / "out.mkv"
    main(["encode", str(sbs_source), "-o", str(output), "-p", "mpeg2"])
    capsys.readouterr()
    assert main(["verify", str(output)]) == 0
    assert main(["verify", str(output), str(sbs_source)]) == 1


def test_errors_are_reported_without_a_traceback(tmp_path, capsys):
    assert (
        main(["encode", str(tmp_path / "missing.mkv"), "-o", str(tmp_path / "x.mkv")])
        == 2
    )
    assert "iglasses:" in capsys.readouterr().err


def test_an_unknown_subcommand_is_refused():
    with pytest.raises(SystemExit):
        main(["denoise"])
