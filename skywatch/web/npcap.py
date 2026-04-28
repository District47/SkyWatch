"""Bundled WiFi-driver helper.

Npcap (https://npcap.com/) is the WinPcap successor; SkyWatch needs it
for the WiFi-monitor-mode Drone Remote ID path. The Nmap Project's
license forbids redistributing the installer in another package, so we
download it on demand the first time the user clicks the install button
and then launch it elevated. Mirrors :mod:`skywatch.web.zadig`.

Exposes:

* ``is_supported()`` — only Windows.
* ``is_installed()`` — checks for ``System32\\Npcap\\wpcap.dll``.
* ``status()`` — small dict for the dashboard.
* ``ensure()`` — downloads the installer if missing.
* ``launch()`` — runs it elevated. The installer is a normal GUI;
  the user clicks through it once and restarts SkyWatch.
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

log = logging.getLogger("skywatch.npcap")

# Pinned to the latest stable build at the time of writing. Always
# fetched from npcap.com (per the license).
_NPCAP_URL = "https://npcap.com/dist/npcap-1.83.exe"
_NPCAP_FILENAME = "npcap-installer.exe"


def is_supported() -> bool:
    return platform.system() == "Windows"


def is_installed() -> Optional[Path]:
    if not is_supported():
        return None
    candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "Npcap" / "wpcap.dll",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wpcap.dll",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _installer_path() -> Optional[Path]:
    if BUNDLED_TOOLS_DIR is not None:
        return BUNDLED_TOOLS_DIR / _NPCAP_FILENAME
    if not is_supported():
        return None
    root = Path(sys.modules["skywatch"].__file__).resolve().parent.parent
    fallback = root / "tools" / "win64"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / _NPCAP_FILENAME


def find_installer() -> Optional[Path]:
    p = _installer_path()
    if p and p.is_file():
        return p
    return None


def status() -> dict:
    installed = is_installed()
    return {
        "supported": is_supported(),
        "installed": installed is not None,
        "installed_path": str(installed) if installed else "",
        "installer_present": find_installer() is not None,
        "installer_path": str(_installer_path()) if _installer_path() else "",
        "url": _NPCAP_URL,
    }


def ensure() -> Path:
    """Download the installer if not already cached locally."""
    if not is_supported():
        raise RuntimeError("Npcap is only used on Windows")
    found = find_installer()
    if found:
        return found
    dest = _installer_path()
    if dest is None:
        raise RuntimeError("could not determine download location for Npcap installer")
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading Npcap from %s -> %s", _NPCAP_URL, dest)
    tmp = dest.with_suffix(".tmp")
    req = urllib.request.Request(_NPCAP_URL, headers={"User-Agent": "SkyWatch"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)
    log.info("Npcap installer saved to %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def launch() -> dict:
    """Launch the Npcap installer elevated. Returns a small status dict."""
    if not is_supported():
        return {"ok": False, "error": "Npcap is only used on Windows"}
    if is_installed():
        return {"ok": True, "note": "Npcap already installed", "already_installed": True}
    try:
        path = ensure()
    except Exception as e:
        return {"ok": False, "error": f"download failed: {e}"}

    import ctypes

    SW_SHOWNORMAL = 1
    rc = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(path), None, str(path.parent), SW_SHOWNORMAL
    )
    if int(rc) <= 32:
        return {"ok": False, "error": f"launch failed (code {int(rc)})", "path": str(path)}
    return {"ok": True, "path": str(path)}
