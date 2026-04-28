"""Installation health check.

Runs a series of self-tests (binaries on PATH, native libraries, Python
modules, data files) and returns a structured report. The dashboard
exposes this under Settings → "Installation Status".

Each check returns a :class:`HealthCheck` with a status of:

* ``ok``    — present and usable
* ``warn``  — missing but optional / has a fallback
* ``fail``  — missing and required for that capability
* ``skip``  — not applicable on this platform

A check should never raise — it always reports a HealthCheck.
"""
from __future__ import annotations

import importlib
import logging
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("skywatch.health")


@dataclass
class HealthCheck:
    name: str
    category: str
    status: str  # ok | warn | fail | skip
    detail: str = ""
    fix_hint: str = ""

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "detail": self.detail,
            "fix_hint": self.fix_hint,
        }


def _module_check(name: str, mod: str, *, category: str, optional: bool = False,
                  hint: str = "") -> HealthCheck:
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "")
        return HealthCheck(name, category, "ok", f"imported{(' v' + ver) if ver else ''}")
    except Exception as e:
        return HealthCheck(
            name, category, "warn" if optional else "fail",
            f"import failed: {e}",
            hint or f"pip install {mod.split('.')[0]}",
        )


def _binary_check(name: str, binary: str, *, category: str, optional: bool = False,
                  hint: str = "") -> HealthCheck:
    found = shutil.which(binary)
    if found:
        return HealthCheck(name, category, "ok", found)
    return HealthCheck(
        name, category, "warn" if optional else "fail",
        f"{binary} not on PATH",
        hint,
    )


def _check_librtlsdr() -> HealthCheck:
    try:
        from rtlsdr.librtlsdr import librtlsdr
        count = librtlsdr.rtlsdr_get_device_count()
        return HealthCheck(
            "librtlsdr (RTL-SDR driver)", "rtl-sdr", "ok",
            f"loaded; {count} device(s) currently visible",
        )
    except OSError as e:
        return HealthCheck(
            "librtlsdr (RTL-SDR driver)", "rtl-sdr", "fail",
            f"DLL load failed: {e}",
            "Drop rtlsdr.dll + libusb-1.0.dll into tools/win64/ (rtl-sdr-blog Windows release).",
        )
    except Exception as e:
        return HealthCheck(
            "librtlsdr (RTL-SDR driver)", "rtl-sdr", "fail",
            f"unexpected error: {e}",
            "",
        )


def _check_npcap() -> HealthCheck:
    if platform.system() != "Windows":
        return HealthCheck("Npcap (WiFi capture driver)", "drone-rid", "skip",
                           "not required on this platform")
    candidates = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "Npcap" / "wpcap.dll",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "wpcap.dll",
    ]
    for p in candidates:
        if p.is_file():
            return HealthCheck("Npcap (WiFi capture driver)", "drone-rid", "ok", str(p))
    return HealthCheck(
        "Npcap (WiFi capture driver)", "drone-rid", "warn",
        "wpcap.dll not found in System32",
        "Install Npcap from https://npcap.com/ — required for WiFi Drone-RID. BLE Drone-RID still works without it.",
    )


def _check_wifi_interfaces() -> HealthCheck:
    try:
        from .remoteid import list_wifi_interfaces
        ifaces = list_wifi_interfaces()
    except Exception as e:
        return HealthCheck("WiFi adapters detected", "drone-rid", "warn",
                           f"enumerate failed: {e}",
                           "scapy may not be installed correctly.")
    if not ifaces:
        return HealthCheck("WiFi adapters detected", "drone-rid", "warn",
                           "no WiFi adapters visible",
                           "Plug in a monitor-mode-capable WiFi adapter (AR9271 / AWUS036NHA / morrownr-driver RTL8812AU). BLE Drone-RID still works.")
    def _label(i):
        if isinstance(i, dict):
            return i.get("description") or i.get("name") or "?"
        return getattr(i, "description", None) or getattr(i, "name", "?")
    return HealthCheck("WiFi adapters detected", "drone-rid", "ok",
                       f"{len(ifaces)} adapter(s): " + ", ".join(_label(i) for i in ifaces[:6]))


def _check_aircraft_db() -> HealthCheck:
    p = Path("data/aircraft.json")
    if not p.is_file():
        return HealthCheck("Aircraft database", "ads-b", "warn",
                           "data/aircraft.json missing",
                           "Click Aircraft → Import in the dashboard, or it will be auto-fetched on first ADS-B start.")
    try:
        size_kb = p.stat().st_size // 1024
        return HealthCheck("Aircraft database", "ads-b", "ok",
                           f"{p} ({size_kb} KB)")
    except Exception as e:
        return HealthCheck("Aircraft database", "ads-b", "warn",
                           f"stat failed: {e}", "")


def _check_zadig() -> HealthCheck:
    if platform.system() != "Windows":
        return HealthCheck("Zadig (driver helper)", "rtl-sdr", "skip",
                           "not required on this platform")
    from .web import zadig
    p = zadig.find()
    if p:
        return HealthCheck("Zadig (driver helper)", "rtl-sdr", "ok", str(p))
    return HealthCheck("Zadig (driver helper)", "rtl-sdr", "warn",
                       "not yet downloaded",
                       "Click 'Install / Replace driver…' in Settings — it auto-downloads on first use.")


def _check_bundled_tools_dir() -> HealthCheck:
    from ._bootstrap import BUNDLED_TOOLS_DIR
    if BUNDLED_TOOLS_DIR is None:
        return HealthCheck("Bundled tools folder", "core", "warn",
                           "tools/<platform>/ not found",
                           "Optional — only needed for the self-contained shippable layout.")
    return HealthCheck("Bundled tools folder", "core", "ok", str(BUNDLED_TOOLS_DIR))


def _check_python() -> HealthCheck:
    v = sys.version_info
    if v < (3, 10):
        return HealthCheck("Python version", "core", "fail",
                           f"{v.major}.{v.minor}.{v.micro}",
                           "Upgrade to Python 3.10 or newer.")
    return HealthCheck("Python version", "core", "ok",
                       f"{v.major}.{v.minor}.{v.micro} on {platform.system()}/{platform.machine()}")


def run_all() -> list[HealthCheck]:
    """Run every registered check. Each one is wrapped so a single broken
    probe can't take the whole report down."""
    checks: list[Callable[[], HealthCheck]] = [
        _check_python,
        _check_bundled_tools_dir,

        # Core Python modules
        lambda: _module_check("FastAPI", "fastapi", category="core"),
        lambda: _module_check("numpy", "numpy", category="core"),
        lambda: _module_check("pyrtlsdr", "rtlsdr", category="rtl-sdr"),

        # RTL-SDR driver
        _check_librtlsdr,
        _check_zadig,

        # ADS-B
        lambda: _module_check("pyModeS (ADS-B decoder)", "pyModeS", category="ads-b"),
        lambda: _binary_check("readsb (legacy ADS-B daemon)", "readsb",
                              category="ads-b", optional=True,
                              hint="Optional — native pure-Python decoder is the default."),
        _check_aircraft_db,

        # AIS
        lambda: _binary_check("AIS-catcher", "AIS-catcher",
                              category="ais", optional=True,
                              hint="Drop AIS-catcher.exe into tools/win64/ — used as the rtl_ais drop-in on Windows."),
        lambda: _binary_check("rtl_ais", "rtl_ais",
                              category="ais", optional=True,
                              hint="Optional — AIS-catcher is the default on Windows. rtl_ais needed only for the Linux/macOS path."),

        # NOAA
        lambda: _binary_check("rtl_fm (NWR + APT capture)", "rtl_fm",
                              category="noaa", optional=False,
                              hint="Drop rtl_fm.exe into tools/win64/ (already bundled in the rtl-sdr-blog release)."),
        lambda: _module_check("sgp4 (satellite tracker)", "sgp4",
                              category="noaa", optional=True),

        # Drone Remote ID
        lambda: _module_check("scapy (WiFi sniffer)", "scapy", category="drone-rid"),
        lambda: _module_check("bleak (Bluetooth LE)", "bleak", category="drone-rid"),
        _check_npcap,
        _check_wifi_interfaces,
    ]

    out: list[HealthCheck] = []
    for fn in checks:
        try:
            out.append(fn())
        except Exception as e:
            log.warning("health check %s raised: %s", getattr(fn, "__name__", "?"), e)
            out.append(HealthCheck(
                getattr(fn, "__name__", "?"), "core", "fail",
                f"check raised: {e}",
            ))
    return out


def summarize(checks: list[HealthCheck]) -> dict:
    counts = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1
    if counts["fail"]:
        overall = "fail"
    elif counts["warn"]:
        overall = "warn"
    else:
        overall = "ok"
    return {"overall": overall, "counts": counts}
