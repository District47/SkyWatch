"""SkyWatch — unified SDR monitoring (Python port of the Go implementation)."""
__version__ = "1.0.0"

# Auto-add a bundled tools folder (if present) to PATH and Windows DLL search.
# Runs at import time so pyrtlsdr, AIS-catcher, rtl_fm, etc. work out of a
# self-contained `<project>/tools/<platform>/` directory with no system install.
from . import _bootstrap  # noqa: F401
