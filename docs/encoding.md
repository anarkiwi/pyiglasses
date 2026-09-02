# Encoding notes

References are to the i-glasses! Developer Kit v1.2 (Virtual i-O, 1995), sections D
and E. That document is third party and is not redistributed here.

## Field sequential stereo

The headset takes ordinary composite video and splits it by field: one field drives
the left panel, the other the right. The video specification (section E) defines the
left eye as the first scanline of the first field, so in a woven progressive-looking
frame the left eye occupies even lines (0, 2, 4, ...) and the right eye odd lines.
`--swap-eyes` inverts that for material authored the other way round, which is also
what the headset's own left/right switch does.

## Per-field resampling phase

The two eyes are not sampled on the same grid. Left-eye line `n` sits at frame line
`2n` and right-eye line `n` at frame line `2n + 1`: the grids are exactly one frame
line apart. Scaling both eyes to the field height with an ordinary centred resizer
and then weaving them therefore gives the right eye one frame line of spurious
*vertical* disparity, which the viewer perceives as eye strain rather than depth,
because the visual system has no use for vertical parallax.

`resample.py` takes an explicit output sample phase for this reason. A centred resize
uses phase 0.5; the top field uses 0.25 and the bottom field 0.75, i.e. a quarter and
three quarters of the way through each pair of frame lines. `weave.FieldWeaver` builds
one vertical matrix per phase, so both eyes land on the frame grid they will actually
be displayed on.

Resampling is expressed as a dense `(dst, src)` matrix per axis and applied with a
matmul, which keeps the per-frame cost to two BLAS calls rather than a Python or numba
per-pixel loop. The kernel is widened when downscaling so that it low passes instead
of aliasing, and the source is edge replicated. Convergence shifts the source window
off the source image, so `source_span` reports which output columns have no real
source behind them and those are filled with the background colour instead of smeared
edge pixels.

## Nothing may filter vertically

Once the frame is woven, adjacent lines belong to different eyes. Any vertical filter
across the frame - a resize, a deinterlacer, a sharpener, a naive chroma subsampler -
averages the two eyes together. That is cross talk, not anti-aliasing, and it shows up
as ghosting or, in the worst case, a flat picture. Every vertical operation in this
package happens before the weave, on one eye at a time.

## 4:2:2 versus 4:2:0

4:2:2 subsamples chroma horizontally only, so each chroma sample stays inside the line
it came from, and therefore inside its own eye. It is the default for every profile
that can use it.

4:2:0 halves chroma vertically too, and libswscale does that across adjacent *frame*
lines - which are different eyes. A generic RGB to 4:2:0 conversion therefore merges
the two eyes' colour and the stereo pair comes back with grey, desaturated ghosting.
MPEG-2 sites 4:2:0 chroma per field for interlaced frame pictures, so the correct
answer is to subsample within each field. `color.py` does exactly this: it converts to
4:4:4 first, then averages chroma only between lines of the same parity, and packs the
result by hand. `to_rgb` reverses it, so `iglasses verify` measures what the decoder
actually has rather than what libswscale would guess.

DVD-Video is 4:2:0 by specification, so the `dvd` profile has to live with 4:2:0. It
still gets field-aware subsampling on the way in, but a player whose chroma upsampler
is not field aware will reintroduce some cross talk. Prefer a 4:2:2 profile wherever
the target allows it.

## Field order

Frames are coded interlaced with the top field first (`AVFieldOrder` value `FIELD_TT`,
plus `setparams=field_mode=tff` on the filter graph and `tff=1` for x264). Top field
first means the field carrying the left eye is emitted first and the headset routes it
to the left panel.

If a file is bottom field first, a compliant player emits the odd lines first and the
eyes are swapped. Swapped eyes are not a subtle defect: near objects appear far and
far objects near, and the picture is uncomfortable rather than obviously broken, which
is why `iglasses verify` treats a non-TFF field order as a hard failure rather than a
warning. It also flags frames that are not marked interlaced at all and field pairs
that are near identical, both of which decode and look fine in 2D while carrying no
stereo at all.

## Geometry: fit, overscan, convergence

`Geometry` in `weave.py` controls how the source picture lands in the output raster.

* `--fit contain` (default) letterboxes to the output display aspect, `cover` crops to
  it, `stretch` distorts to it. The destination rectangle is snapped so that its top
  line and its height are even, otherwise the eyes would land on the wrong parity.
* `--overscan` crops that fraction off every edge, for sets and headsets that lose the
  border of the raster.
* `--convergence` adds that many output pixels of horizontal disparity by shifting the
  two eyes' source windows in opposite directions by half that amount each. The sign
  convention is that **positive convergence adds disparity and sits the scene behind
  the screen** (uncrossed parallax); negative pulls it towards the viewer (crossed).
  The test pattern's parallax ruler uses the same convention.

The eye aspect ratio is deduced from the source unless `--eye-aspect` overrides it.
Half-width side by side and half-height over/under material squeezes a full-aspect
image into half a frame, so the pixel dimensions alone are ambiguous; both readings are
scored against the aspect ratios real material is authored to and the closer wins.

## Known limitation: FFV1 in Matroska and pixel aspect

PyAV does not carry the sample aspect ratio through to the Matroska container for FFV1,
so a lossless `ffv1` master in a `.mkv` written by this tool decodes with a 1:1 pixel
aspect regardless of what the `ntsc` or `pal` format signals. `iglasses verify` reports
this as a note, not an issue.

This matters only for software players, which will show a 720x480 or 720x576 frame with
the wrong shape. It does not affect real composite output: a hardware path resamples the
active line to the analogue line period, so the picture reaches the headset correctly
shaped whatever the container claimed. If a software player has to show the right shape
for a lossless master, use a square pixel format - `ntsc-square` (640x480) or
`pal-square` (768x576) - where the coded raster is already the display raster.
