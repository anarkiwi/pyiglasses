# Development

## Dependencies

The only runtime dependencies are:

* **av** (PyAV) - the wheels bundle their own ffmpeg libraries, so no system ffmpeg
  install or `pkg-config` setup is needed;
* **numpy**;
* **pyserial** - the head tracker transport. Nothing else in the package imports it, and
  it is imported lazily, so the video tools work whether or not a serial port exists.

Development extras (`pytest`, `pytest-xdist`, `pytest-cov`, `black`, `pylint`) come from
the `dev` optional dependency group:

```sh
pip install -e '.[dev]'
```

## Tests

```sh
pytest
```

`pyproject.toml` configures the run: `-n auto` distributes tests across cores via
pytest-xdist, and coverage is measured over `pyiglasses` with `--cov-fail-under=85`, so
a run with less than 85% line coverage fails even if every test passes. `term-missing`
prints the uncovered lines.

Tests must stay fast. Encode tests should use small frame counts (the `max_frames`
argument to `encode_stereo`, or `--frames` on the command line) rather than encoding
real-time durations.

## Formatting

```sh
black .
black --check .
```

Black is authoritative; do not hand-format around it.

## Linting

```sh
pylint pyiglasses
```

The pylint configuration lives in `pyproject.toml`: line length 100, with a small set of
size and duplication checks disabled. Unused imports and unused variables are not
disabled and must be fixed.

## CI

`.github/workflows/ci.yml` runs the test suite on Python 3.11, 3.12 and 3.13 on
ubuntu-latest, plus a separate job running `black --check .` and `pylint pyiglasses`.
Dependabot (`.github/dependabot.yml`) checks pip and GitHub Actions dependencies weekly.
