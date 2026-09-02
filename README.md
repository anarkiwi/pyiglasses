# pyiglasses

Drivers and tools for the 1995 Virtual i-O i-glasses! head mounted display.

## Status

Field sequential 3D video encoder: implemented. Head tracker (RS-232) driver: not yet
written, see [docs/hardware.md](docs/hardware.md).

## Install

```sh
pip install -e .
```

## Usage

```sh
# list formats, profiles and layouts
iglasses formats

# side by side source (the default layout) to NTSC MPEG-2
iglasses encode movie_sbs.mp4 -o movie.mkv

# two separate eye files to PAL, lossless
iglasses encode left.mov --right right.mov -o movie.mkv -f pal -p ffv1

# over/under source to a DVD compliant stream, cropped and pushed back
iglasses encode movie_ou.mkv -l ou -o movie.mpg -p dvd \
    --fit cover --overscan 0.03 --convergence 8 --kernel catrom

# eyes the wrong way round on your headset switch
iglasses encode movie_sbs.mp4 -o movie.mkv --swap-eyes

# 30 seconds of stereo test pattern for hardware bring up
iglasses pattern -o pattern.mkv -d 30 -f ntsc -p ffv1

# check an encode is really field sequential 3D
iglasses verify movie.mkv pattern.mkv
```

## Video formats

| name | frame | rate | pixel aspect | lines per eye | display aspect |
| --- | --- | --- | --- | --- | --- |
| `ntsc` (default) | 720x480 | 30000/1001 | 8:9 | 240 | 4:3 |
| `pal` | 720x576 | 25 | 16:15 | 288 | 4:3 |
| `ntsc-square` | 640x480 | 30000/1001 | 1:1 | 240 | 4:3 |
| `pal-square` | 768x576 | 25 | 1:1 | 288 | 4:3 |

## Encoding profiles

| name | codec | pixel format | container | audio | notes |
| --- | --- | --- | --- | --- | --- |
| `mpeg2` (default) | mpeg2video | yuv422p | .mkv | flac | 15 Mbit/s, playback and capture |
| `ffv1` | ffv1 | yuv422p | .mkv | flac | lossless intra-only master |
| `dvd` | mpeg2video | yuv420p | .mpg | mp2 | DVD-Video parameters, 6 Mbit/s |
| `h264` | libx264 | yuv422p | .mp4 | aac | CRF 18, `tff=1` |

Source layouts: `sbs` (default), `ou`, `separate` (implied by `--right`).
Resampling kernels: `lanczos` (default), `catrom`, `triangle`, `box`.

## How it works

* The left eye is the first scanline of the first field, so it owns even frame lines
  and the right eye owns odd ones.
* Each eye is resampled onto its own field's vertical grid (phase 0.25 and 0.75), so
  weaving introduces no vertical disparity.
* Resampling is a pair of dense matrices applied as BLAS matmuls, one per axis.
* Output is coded interlaced, top field first, and nothing filters vertically across
  the woven frame.
* 4:2:0 profiles subsample chroma within each field rather than across the two eyes.
* `iglasses verify` re-decodes a file and checks field order, interlaced flagging,
  field separation and disparity.

## Documentation

* [docs/encoding.md](docs/encoding.md) - why the encoder does what it does.
* [docs/hardware.md](docs/hardware.md) - the i-glasses! hardware and the tracker.
* [docs/development.md](docs/development.md) - tests, formatting and linting.

## Licence

Apache-2.0.
