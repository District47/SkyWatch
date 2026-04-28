"""Microsoft Visual C++ Redistributable installer helper.

AIS-catcher.exe (and a few other bundled tools) link against
``MSVCP140.dll`` / ``VCRUNTIME140.dll`` / ``VCRUNTIME140_1.dll`` from
the Visual Studio 2015-2022 runtime. If the Redistributable hasn't been
installed, those processes exit with ``0xC0000135 STATUS_DLL_NOT_FOUND``
the moment the dashboard tries to start AIS.

We don't redistribute the DLLs ourselves; instead, on demand we fetch
the official ``vc_redist.x64.exe`` from Microsoft's stable permalink and
launch it elevated. Mirrors :mod:`skywatch.web.zadig` / :mod:`npcap`.
"""
from __future__ import annotations

import logging
import os
import platform
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from .._bootstrap import BUNDLED_TOOLS_DIR

log = logging.getLogger("skywatch.vcredist")

# Microsoft's stable permalink — always points to the latest VS 2015-2022
# x64 Redistributable.
_VCREDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
_VCREDIST_FILENAME = "vc_redist.x64.exe"
_REQUIRED_DLLS = ("MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll")


def is_supported() -> bool:
    return platform.system() == "Windows"


def is_installed() -> bool:
    if not is_supported():
        return False
    sysdir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
    return all((sysdir / d).is_file() for d in _REQUIRED_DLLS)


def _installer_path() -> Optional[Path]:
    if BUNDLED_TOOLS_DIR is not None:
        return BUNDLED_TOOLS_DIR / _VCREDIST_FILENAME
    if not is_supported():
        return None
    root = Path(sys.modules["skywatch"].__file__).resolve().parent.parent
    fallback = root / "tools" / "win64"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / _VCREDIST_FILENAME


def find_installer() -> Optional[Path]:
    p = _installer_path()
    if p and p.is_file():
        return p
    return None


def status() -> dict:
    sysdir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" if is_supported() else None
    missing = []
    if sysdir is not None:
        missing = [d for d in _REQUIRED_DLLS if not (sysdir / d).is_file()]
    return {
        "supported": is_supported(),
        "installed": is_installed(),
        "missing_dlls": missing,
        "installer_present": find_installer() is not None,
        "installer_path": str(_installer_path()) if _installer_path() else "",
        "url": _VCREDIST_URL,
    }


def ensure() -> Path:
    """Download vc_redist.x64.exe if not cached locally."""
    if not is_supported():
        raise RuntimeError("vc_redist is only used on Windows")
    found = find_installer()
    if found:
        return found
    dest = _installer_path()
    if dest is None:
        raise RuntimeError("could not determine download location for vc_redist.x64.exe")
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading vc_redist from %s -> %s", _VCREDIST_URL, dest)
    tmp = dest.with_suffix(".tmp")
    req = urllib.request.Request(_VCREDIST_URL, headers={"User-Agent": "SkyWatch"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)
    log.info("vc_redist installer saved to %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def launch() -> dict:
    """Launch the redistributable installer elevated."""
    if not is_supported():
        return {"ok": False, "error": "vc_redist is only used on Windows"}
    if is_installed():
        return {"ok": True, "note": "VC++ Redistributable already installed", "already_installed": True}
    try:
        path = ensure()
    except Exception as e:
        return {"ok": False, "error": f"download failed: {e}"}

    import ctypes

    SW_SHOWNORMAL = 1
    # Default GUI flow lets the user click through. Power users can pass
    # /quiet themselves if they want a silent install.
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(path), None, str(path.parent), SW_SHOWNORMAL
    )
    if int(rc) <= 32:
        return {"ok": False, "error": f"launch failed (code {int(rc)})", "path": str(path)}
    return {"ok": True, "path": str(path)}
