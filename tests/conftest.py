"""Shared fixtures: small synthetic stereo sources.

Each xdist worker is a process of its own, and BLAS and libavcodec both size
their thread pools from the core count, so the workers together ask for far more
threads than the machine has and thread creation starts failing.  The frames
here are small enough that one thread each is faster anyway.  This has to happen
before numpy is imported.
"""

import os

for _pool in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_pool, "1")

import av
import numpy as np
import pytest

SOURCE_FRAMES = 6


def eye_image(height, width, offset, colour):
    """A frame with one bright square at a known horizontal offset."""
    image = np.zeros((height, width, 3), np.uint8)
    top, left = height // 3, width // 3 + offset
    image[top : top + height // 4, left : left + width // 6] = colour
    return image


def write_video(path, frames, rate=24, audio=False):
    """Write RGB frames to a lossless file, optionally with a tone."""
    with av.open(str(path), "w") as container:
        stream = container.add_stream("ffv1", rate=rate)
        stream.width, stream.height = frames[0].shape[1], frames[0].shape[0]
        stream.pix_fmt = "yuv444p"
        sound = None
        if audio:
            sound = container.add_stream("flac", rate=48000)
            sound.layout = "stereo"
        for index, image in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = index
            for packet in stream.encode(frame):
                container.mux(packet)
        if sound is not None:
            samples = int(48000 * len(frames) / rate)
            tone = (np.sin(np.arange(samples) / 8.0) * 8000).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(
                np.repeat(tone[None, :], 2, axis=0).reshape(1, -1),
                format="s16",
                layout="stereo",
            )
            frame.sample_rate = 48000
            frame.pts = 0
            resampler = av.AudioResampler(
                format=sound.format,
                layout="stereo",
                rate=48000,
                frame_size=sound.frame_size,
            )
            for resampled in list(resampler.resample(frame)) + list(
                resampler.resample(None)
            ):
                for packet in sound.encode(resampled):
                    container.mux(packet)
            for packet in sound.encode():
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


@pytest.fixture(name="disparity")
def fixture_disparity():
    """Horizontal offset between the eyes in the synthetic sources."""
    return 12


@pytest.fixture(name="sbs_source")
def fixture_sbs_source(tmp_path_factory, disparity):
    """A side by side source: 320x240 frames of two 160x240 eyes."""
    frames = []
    for index in range(SOURCE_FRAMES):
        packed = np.zeros((240, 320, 3), np.uint8)
        packed[:, :160] = eye_image(240, 160, index, (255, 0, 0))
        packed[:, 160:] = eye_image(240, 160, index - disparity, (0, 0, 255))
        frames.append(packed)
    return write_video(tmp_path_factory.mktemp("src") / "sbs.mkv", frames, audio=True)


@pytest.fixture(name="eye_sources")
def fixture_eye_sources(tmp_path_factory, disparity):
    """Two separate eye files."""
    directory = tmp_path_factory.mktemp("eyes")
    paths = []
    for offset, colour in ((0, (255, 0, 0)), (-disparity, (0, 0, 255))):
        frames = [
            eye_image(240, 320, index + offset, colour)
            for index in range(SOURCE_FRAMES)
        ]
        paths.append(write_video(directory / f"eye{offset}.mkv", frames, rate=30))
    return tuple(paths)


@pytest.fixture(name="flat_source")
def fixture_flat_source(tmp_path_factory):
    """A packed source whose two halves are identical: no stereo at all."""
    frames = []
    for index in range(SOURCE_FRAMES):
        eye = eye_image(240, 160, index, (200, 200, 200))
        frames.append(np.concatenate([eye, eye], axis=1))
    return write_video(tmp_path_factory.mktemp("flat") / "flat.mkv", frames)
