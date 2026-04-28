"""Auto-discover bundled tool binaries inside the project tree.

If `<project_root>/tools/<platform>/` exists, this module prepends it to
the process PATH (so `subprocess.spawn` finds AIS-catcher.exe / rtl_fm.exe
without a system install) and registers it as a Windows DLL search
directory (so ctypes.CDLL — what pyrtlsdr uses — finds librtlsdr.dll).

The result: a self-contained shippable folder. Drop your binaries into
`tools/win64/` (or `tools/linux64/`, `tools/darwin-arm64/`), zip the whole
project, and recipients only need Python + `pip install -r requirements.txt`.
"""
from __future__ import annotations

import logging
import os
import platform
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger("skywatch.bootstrap")


def _platform_key() -> str:
    sys_name = platform.system().lower()
    if sys_name == "windows":
        return "win64" if sys.maxsize > 2 ** 32 else "win32"
    if sys_name == "darwin":
        return "darwin-arm64" if platform.machine() in ("arm64", "aarch64") else "darwin-x64"
    return "linux64"


def configure_bundled_tools() -> Optional[Path]:
    """Look for `<project_root>/tools/<platform>/` and wire it into PATH +
    Windows DLL search. Returns the discovered path or None.
    """
    # __file__ = .../skywatch/_bootstrap.py — project root is two levels up.
    root = Path(__file__).resolve().parent.parent
    tools = root / "tools" / _platform_key()
    if not tools.is_dir():
        return None

    # Prepend so we win over any system-wide install.
    current = os.environ.get("PATH", "")
    if str(tools) not in current.split(os.pathsep):
        os.environ["PATH"] = str(tools) + os.pathsep + current

    # On Windows + Python 3.8+, ctypes ignores PATH for DLL discovery.
    # Register the directory explicitly so librtlsdr.dll loads.
    if platform.system() == "Windows" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(tools))
        except (OSError, FileNotFoundError) as e:
            log.debug("add_dll_directory(%s) failed: %s", tools, e)

    log.info("bundled tools: %s", tools)
    return tools


# Run on import so all later subprocess and ctypes calls already see it.
BUNDLED_TOOLS_DIR = configure_bundled_tools()
