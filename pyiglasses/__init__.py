"""Drivers and tools for Virtual i-O i-glasses! head mounted displays."""

from .encode import PROFILES, EncodeProfile, InterlacedWriter, get_profile
from .formats import FORMATS, VideoFormat, get_format
from .pipeline import EncodeResult, encode_stereo
from .stereo import LAYOUTS, get_layout
from .verify import VerifyReport, verify
from .weave import FieldWeaver, Geometry

__version__ = "0.1.0"

__all__ = [
    "EncodeProfile",
    "EncodeResult",
    "FORMATS",
    "FieldWeaver",
    "Geometry",
    "InterlacedWriter",
    "LAYOUTS",
    "PROFILES",
    "VerifyReport",
    "VideoFormat",
    "encode_stereo",
    "get_format",
    "get_layout",
    "get_profile",
    "verify",
]
