"""Colour conversion that keeps chroma inside its own field.

libswscale subsamples 4:2:0 chroma across adjacent frame lines.  In a field
sequential frame those lines are different eyes, so a generic RGB to 4:2:0
conversion averages the two eyes' colour together and the stereo pair comes back
grey.  MPEG-2 sites 4:2:0 chroma per field for interlaced frame pictures, so the
subsampling is done here, within each field, and the eyes stay separate.  4:2:2
and 4:4:4 subsample only horizontally and need no special handling.
"""

import av
import numpy as np

FIELD_CHROMA_FORMATS = ("yuv420p",)


def _subsample_horizontal(plane):
    return ((plane[:, 0::2].astype(np.uint16) + plane[:, 1::2] + 1) >> 1).astype(
        np.uint8
    )


def _subsample_vertical_by_field(plane):
    """Halve a chroma plane vertically, averaging only within a field."""
    height = plane.shape[0]
    if height % 4:
        raise ValueError("field aware chroma subsampling needs a height divisible by 4")
    out = np.empty((height // 2, plane.shape[1]), np.uint8)
    for parity in (0, 1):
        rows = plane[parity::2]
        out[parity::2] = ((rows[0::2].astype(np.uint16) + rows[1::2] + 1) >> 1).astype(
            np.uint8
        )
    return out


def _upsample_vertical_by_field(plane, height):
    """Undo :func:`_subsample_vertical_by_field`."""
    out = np.empty((height, plane.shape[1]), np.uint8)
    for parity in (0, 1):
        out[parity::2] = np.repeat(plane[parity::2], 2, axis=0)
    return out


def to_video_frame(rgb, pix_fmt):
    """Convert an RGB frame to ``pix_fmt`` without mixing chroma across fields."""
    frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(rgb), format="rgb24")
    frame = frame.reformat(
        format="yuv444p", dst_colorspace="ITU601", dst_color_range="MPEG"
    )
    if pix_fmt not in FIELD_CHROMA_FORMATS:
        return frame.reformat(format=pix_fmt) if pix_fmt != "yuv444p" else frame
    luma, blue, red = frame.to_ndarray()
    planes = [luma] + [
        _subsample_vertical_by_field(_subsample_horizontal(plane))
        for plane in (blue, red)
    ]
    packed = np.concatenate([plane.reshape(-1) for plane in planes])
    out = av.VideoFrame.from_ndarray(packed.reshape(-1, luma.shape[1]), format=pix_fmt)
    out.colorspace = frame.colorspace
    out.color_range = frame.color_range
    return out


def to_rgb(frame):
    """Decode a frame to RGB, upsampling 4:2:0 chroma within each field."""
    if frame.format.name not in FIELD_CHROMA_FORMATS:
        return frame.to_ndarray(format="rgb24")
    height, width = frame.height, frame.width
    packed = frame.to_ndarray()
    luma = packed[:height]
    chroma = packed[height:].reshape(2, height // 2, width // 2)
    planes = [
        np.repeat(_upsample_vertical_by_field(plane, height), 2, axis=1)
        for plane in chroma
    ]
    full = av.VideoFrame.from_ndarray(np.stack([luma] + planes), format="yuv444p")
    full.colorspace = frame.colorspace
    full.color_range = frame.color_range
    return full.reformat(
        format="rgb24", src_colorspace="ITU601", src_color_range="MPEG"
    ).to_ndarray(format="rgb24")
