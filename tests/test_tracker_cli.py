"""The track subcommand."""

import pytest

from pyiglasses.cli import main

# The simulator answers instantly, so a short timeout only shortens failures.
FAST = ["--timeout", "0.05"]


def track(*arguments):
    """Run the track subcommand against the built in simulator."""
    return main(["track", "--simulate", *arguments, *FAST])


def test_info_reports_the_version_and_stops(capsys):
    assert track("--info") == 0
    out = capsys.readouterr().out
    assert "VIRTUAL I-O" in out and "self test passed" in out
    assert out.count("\n") == 1


def test_polling_prints_the_requested_number_of_readings(capsys):
    assert track("-n", "4", "--filter", "3,3") == 0
    assert len(capsys.readouterr().out.strip().split("\n")) == 5


@pytest.mark.parametrize("mode", ["euler", "cooked", "raw"])
def test_every_orientation_mode_streams(capsys, mode):
    assert track("-m", mode, "--continuous", "-n", "3", "--format", "ascii") == 0
    assert len(capsys.readouterr().out.strip().split("\n")) == 4


def test_mouse_mode_prints_deltas(capsys):
    assert (
        track(
            "-m",
            "mouse",
            "--continuous",
            "-n",
            "3",
            "--filter",
            "3,3",
            "--mouse",
            "2,0",
        )
        == 0
    )
    rows = capsys.readouterr().out.strip().split("\n")[1:]
    assert all(len(row.split()) == 4 for row in rows)


def test_readings_can_be_written_as_csv(tmp_path, capsys):
    path = tmp_path / "track.csv"
    assert track("-n", "3", "--csv", str(path)) == 0
    capsys.readouterr()
    lines = path.read_text(encoding="ascii").strip().split("\n")
    assert lines[0] == "yaw,pitch,roll"
    assert len(lines) == 4
    assert all(len(line.split(",")) == 3 for line in lines[1:])


def test_a_fixed_rate_skips_the_sweep(capsys):
    assert track("--baud", "9600", "--info") == 0
    assert "9600 bps" in capsys.readouterr().out


def test_a_rate_the_tracker_is_not_using_fails(capsys):
    assert track("--baud", "1200", "--info") == 2
    assert "no tracker answered" in capsys.readouterr().err


def test_a_port_or_the_simulator_is_required(capsys):
    assert main(["track"]) == 2
    assert "--simulate" in capsys.readouterr().err


@pytest.mark.parametrize(
    "option",
    [["--filter", "x"], ["--filter", "9,9"], ["--filter", "3,3", "--mouse", "1"]],
)
def test_bad_options_are_reported(capsys, option):
    assert track("-n", "1", *option) == 2
    assert "iglasses:" in capsys.readouterr().err


def test_early_firmware_is_called_out(capsys, monkeypatch):
    import functools

    from pyiglasses import cli
    from pyiglasses.tracker.simulator import SimulatedTracker

    monkeypatch.setattr(
        cli, "SimulatedTracker", functools.partial(SimulatedTracker, firmware=1.002)
    )
    assert track("--info") == 0
    assert "predates 001.003" in capsys.readouterr().out


def test_interrupting_a_stream_stops_cleanly(capsys, tmp_path):
    from pyiglasses.cli import _report
    from pyiglasses.tracker.protocol import DataMode

    def readings():
        raise KeyboardInterrupt
        yield  # pylint: disable=unreachable

    _report(readings(), DataMode.EULER, str(tmp_path / "partial.csv"))
    assert capsys.readouterr().out == ""
    assert (tmp_path / "partial.csv").read_text(encoding="ascii") == "yaw,pitch,roll\n"
