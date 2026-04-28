"""Bundled USB-driver helper.

Zadig (https://zadig.akeo.ie/) is the de-facto tool for binding the WinUSB
driver to RTL-SDR dongles on Windows. We don't redistribute the binary
(GPLv3 + driver-signing chain considerations); instead, on first use we
download it into ``tools/win64/`` and launch it with UAC elevation so the
user never has to leave the dashboard.

Exposes:

* ``is_supported()`` — only Windows is targeted.
* ``status()`` — present / supported / version path.
* ``ensure()`` — downloads the binary if missing.
* ``launch()`` — runs it elevated. Returns when the UAC dialog closes
  (the Zadig window itself stays up until the user dismisses it).
"""
from __future__ import annotations

import logging
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from .._bootstrap import BUNDLED_TOOLS_DIR

log = logging.getLogger("skywatch.zadig")

# Pinned to the latest official build at the time of writing. The akeo.ie
# homepage redirects to the same asset on GitHub releases.
_ZADIG_URL = "https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe"
_ZADIG_FILENAME = "zadig.exe"


def is_supported() -> bool:
    return platform.system() == "Windows"


def _target_path() -> Optional[Path]:
    if BUNDLED_TOOLS_DIR is not None:
        return BUNDLED_TOOLS_DIR / _ZADIG_FILENAME
    # Fallback when running from a layout without `tools/<plat>/`: drop
    # alongside the package so it still works.
    if not is_supported():
        return None
    root = Path(sys.modules["skywatch"].__file__).resolve().parent.parent
    fallback = root / "tools" / "win64"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / _ZADIG_FILENAME


def find() -> Optional[Path]:
    p = _target_path()
    if p and p.is_file():
        return p
    return None


def status() -> dict:
    p = _target_path()
    found = find()
    return {
        "supported": is_supported(),
        "present": found is not None,
        "path": str(found) if found else (str(p) if p else ""),
        "url": _ZADIG_URL,
    }


def ensure() -> Path:
    """Download Zadig if not already present. Returns the local path."""
    if not is_supported():
        raise RuntimeError("Zadig is only used on Windows")
    found = find()
    if found:
        return found
    dest = _target_path()
    if dest is None:
        raise RuntimeError("could not determine download location for zadig.exe")
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading Zadig from %s -> %s", _ZADIG_URL, dest)
    tmp = dest.with_suffix(".tmp")
    req = urllib.request.Request(_ZADIG_URL, headers={"User-Agent": "SkyWatch"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)
    log.info("Zadig saved to %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def launch() -> dict:
    """Launch Zadig with UAC elevation. Returns a small status dict."""
    if not is_supported():
        return {"ok": False, "error": "Zadig is only used on Windows"}
    try:
        path = ensure()
    except Exception as e:
        return {"ok": False, "error": f"download failed: {e}"}

    import ctypes

    # ShellExecuteW with verb 'runas' triggers the UAC prompt. Return
    # codes <=32 are errors per the Win32 docs.
    SW_SHOWNORMAL = 1
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(path), None, str(path.parent), SW_SHOWNORMAL
    )
    if int(rc) <= 32:
        # 5 = SE_ERR_ACCESSDENIED (user clicked No on UAC).
        return {"ok": False, "error": f"launch failed (code {int(rc)})", "path": str(path)}
    return {"ok": True, "path": str(path)}
