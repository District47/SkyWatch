"""Drone Remote ID receiver. Mirrors internal/remoteid/remoteid.go.

Capture WiFi management frames (beacon / probe-response) and look for the
ASTM F3411 vendor-specific information element (OUI fa:0b:bc). When a
Location, BasicID, SelfID, OperatorID, or System message is found, fields
are accumulated into a Target with type='drone'.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from ..tracker import Target, Tracker, TYPE_DRONE

log = logging.getLogger("skywatch.remoteid")

# ASTM International OUI used by Open Drone ID.
_VENDOR_OUI = bytes([0xFA, 0x0B, 0xBC])
_IE_VENDOR_SPECIFIC = 221

# Open Drone ID message types (upper nibble of first byte).
_MSG_BASIC_ID = 0x0
_MSG_LOCATION = 0x1
_MSG_AUTH = 0x2
_MSG_SELF_ID = 0x3
_MSG_SYSTEM = 0x4
_MSG_OPERATOR_ID = 0x5
_MSG_PACK = 0xF


@dataclass
class _DroneState:
    uas_id: str = ""
    operator_id: str = ""
    description: str = ""
    lat: float = 0.0
    lon: float = 0.0
    altitude_m: float = 0.0
    speed_kt: float = 0.0
    heading: float = 0.0
    op_lat: float = 0.0
    op_lon: float = 0.0


@dataclass
class RemoteIDConfig:
    interface: str = ""
    auto_monitor: bool = True
    channel: int = 6  # 0 = hop 1/6/11


def list_wifi_interfaces() -> list[dict]:
    """Return all network interfaces with their friendly names + wireless guess.

    Tries scapy's `conf.ifaces` (gives nice names + Windows GUID device path),
    then falls back to `get_if_list()` if scapy didn't populate ifaces yet.
    """
    out: list[dict] = []
    wifi_kw = ("wi-fi", "wifi", "wireless", "wlan", "802.11", "wlp", "wlx", "ath", "rtl", "alfa")

    # Path 1: scapy's high-level interface objects (best names).
    try:
        from scapy.all import conf  # type: ignore  # noqa: F401  triggers init
        ifaces = list(conf.ifaces.values())
    except Exception as e:
        log.debug("scapy conf.ifaces unavailable: %s", e)
        ifaces = []

    seen: set[str] = set()
    for iface in ifaces:
        try:
            description = (getattr(iface, "description", None)
                           or getattr(iface, "name", "")
                           or "").strip()
            # Prefer the OS-level handle that scapy/Npcap will accept.
            scapy_name = (getattr(iface, "network_name", None)
                          or getattr(iface, "name", "")
                          or "").strip()
            if not scapy_name or scapy_name in seen:
                continue
            seen.add(scapy_name)
            blob = (description + " " + scapy_name).lower()
            wireless = any(kw in blob for kw in wifi_kw)
            out.append({
                "name": scapy_name,
                "description": description or scapy_name,
                "wireless": wireless,
            })
        except Exception:
            continue

    # Path 2: fallback to raw get_if_list() if path 1 produced nothing.
    if not out:
        try:
            from scapy.all import get_if_list  # type: ignore
            for raw in get_if_list():
                if not raw or raw in seen:
                    continue
                seen.add(raw)
                wireless = any(kw in raw.lower() for kw in wifi_kw)
                out.append({"name": raw, "description": raw, "wireless": wireless})
        except Exception as e:
            log.debug("get_if_list fallback failed: %s", e)

    out.sort(key=lambda d: (not d["wireless"], d["description"].lower()))
    return out


def parse_remote_id_ie(payload: bytes) -> list[tuple[int, bytes]]:
    """Given a vendor-specific IE payload (after the 3-byte OUI), return
    list of (msg_type, body) tuples. Handles MessagePack (0xF) by recursion.
    """
    out: list[tuple[int, bytes]] = []
    if len(payload) < 1:
        return out
    msg_type = (payload[0] >> 4) & 0x0F
    if msg_type == _MSG_PACK:
        if len(payload) < 2:
            return out
        count = payload[1]
        body = payload[2:]
        # Each packed message is 25 bytes per ASTM F3411-22a.
        for i in range(count):
            sub = body[i * 25 : (i + 1) * 25]
            if not sub:
                break
            out.append(((sub[0] >> 4) & 0x0F, sub))
        return out
    out.append((msg_type, payload))
    return out


def _decode_ascii(b: bytes) -> str:
    try:
        return b.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
    except Exception:
        return ""


def _apply_message(state: _DroneState, msg_type: int, body: bytes) -> bool:
    """Update state from one Open Drone ID message. Returns True if the
    drone has at least an ID + a position (publishable)."""
    if msg_type == _MSG_BASIC_ID:
        if len(body) >= 21:
            state.uas_id = _decode_ascii(body[1:21])
    elif msg_type == _MSG_LOCATION:
        if len(body) >= 18:
            heading_byte = body[1]
            speed_raw = struct.unpack_from("<H", body, 2)[0]
            lat_raw = struct.unpack_from("<i", body, 6)[0]
            lon_raw = struct.unpack_from("<i", body, 10)[0]
            press_alt = struct.unpack_from("<H", body, 14)[0]
            geo_alt = struct.unpack_from("<H", body, 16)[0]
            # Per ASTM: heading 0..360 mapped to byte 0..255; speed in 0.25 m/s.
            state.heading = (heading_byte / 255.0) * 360.0
            speed_ms = speed_raw * 0.25
            state.speed_kt = speed_ms * 1.94384
            state.lat = lat_raw * 1e-7
            state.lon = lon_raw * 1e-7
            # Altitude: value * 0.5 - 1000 meters.
            state.altitude_m = (geo_alt or press_alt) * 0.5 - 1000.0
    elif msg_type == _MSG_SELF_ID:
        if len(body) >= 24:
            state.description = _decode_ascii(body[1:24])
    elif msg_type == _MSG_OPERATOR_ID:
        if len(body) >= 21:
            state.operator_id = _decode_ascii(body[1:21])
    elif msg_type == _MSG_SYSTEM:
        if len(body) >= 9:
            op_lat = struct.unpack_from("<i", body, 1)[0]
            op_lon = struct.unpack_from("<i", body, 5)[0]
            state.op_lat = op_lat * 1e-7
            state.op_lon = op_lon * 1e-7
    return bool(state.uas_id and (state.lat or state.lon))


class RemoteID:
    def __init__(self, cfg: RemoteIDConfig, tracker: Tracker) -> None:
        self.cfg = cfg
        self.tracker = tracker
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._states: dict[str, _DroneState] = {}
        # Counters surfaced by the dashboard / log so users can verify the
        # sniffer is actually receiving traffic.
        self.frames_total = 0
        self.frames_mgmt = 0   # beacons + probe responses (the kind we care about)
        self.frames_rid = 0    # ones containing an Open Drone ID vendor IE
        self.last_frame_at = 0.0
        self.last_rid_at = 0.0

    async def start(self) -> None:
        if not self.cfg.interface:
            log.info("remoteid disabled (no -wifi interface configured)")
            return
        if self._task and not self._task.done():
            return
        if self.cfg.auto_monitor:
            try:
                self._enable_monitor_mode()
            except Exception as e:
                log.warning("monitor mode setup failed: %s", e)
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="remoteid-run")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    def _enable_monitor_mode(self) -> None:
        if platform.system() != "Linux":
            log.info("monitor mode auto-config only supported on Linux; assuming %s already in monitor mode", self.cfg.interface)
            return
        if not shutil.which("ip") or not shutil.which("iw"):
            log.warning("ip/iw not found; cannot configure monitor mode")
            return
        iface = self.cfg.interface
        subprocess.run(["ip", "link", "set", iface, "down"], check=False)
        subprocess.run(["iw", "dev", iface, "set", "type", "monitor"], check=False)
        subprocess.run(["ip", "link", "set", iface, "up"], check=False)
        if self.cfg.channel and self.cfg.channel > 0:
            subprocess.run(["iw", "dev", iface, "set", "channel", str(self.cfg.channel)], check=False)

    async def _run(self) -> None:
        # scapy is sync-only; offload to a thread.
        await asyncio.get_event_loop().run_in_executor(None, self._sniff_blocking)

    def _sniff_blocking(self) -> None:
        try:
            from scapy.all import sniff  # type: ignore
            from scapy.layers.dot11 import Dot11Beacon, Dot11ProbeResp, Dot11Elt  # type: ignore
        except Exception as e:
            log.error("scapy unavailable: %s", e)
            return

        import time as _time
        last_log = _time.monotonic()

        def handler(pkt) -> None:
            nonlocal last_log
            self.frames_total += 1
            self.last_frame_at = _time.time()
            try:
                if not (pkt.haslayer(Dot11Beacon) or pkt.haslayer(Dot11ProbeResp)):
                    return
                self.frames_mgmt += 1
                elt = pkt.getlayer(Dot11Elt)
                while elt is not None:
                    if elt.ID == _IE_VENDOR_SPECIFIC and bytes(elt.info)[:3] == _VENDOR_OUI:
                        self.frames_rid += 1
                        self.last_rid_at = _time.time()
                        body = bytes(elt.info)[3:]
                        for msg_type, sub in parse_remote_id_ie(body):
                            self._ingest_message(msg_type, sub)
                    elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None
            except Exception as e:
                log.debug("RID parse error: %s", e)
            # Heartbeat so the user can see the sniffer is alive.
            now = _time.monotonic()
            if (now - last_log) >= 15.0:
                log.info("remoteid sniff: %d frames (%d mgmt, %d Drone-RID) on %s",
                         self.frames_total, self.frames_mgmt, self.frames_rid, self.cfg.interface)
                last_log = now

        try:
            sniff(iface=self.cfg.interface, prn=handler, store=False, stop_filter=lambda _p: self._stop.is_set())
        except Exception as e:
            log.error("WiFi sniff failed: %s", e)

    def _ingest_message(self, msg_type: int, body: bytes) -> None:
        # Use a temporary state per packet — flush whenever we have ID + position.
        # The Go version accumulates against the most recent UAS, which is fine
        # for a single-drone scene; we mirror that.
        key = "_current"
        st = self._states.setdefault(key, _DroneState())
        ready = _apply_message(st, msg_type, body)
        if ready:
            target = Target(
                id=f"DRONE-{st.uas_id}",
                type=TYPE_DRONE,
                callsign=st.uas_id,
                drone_id=st.uas_id,
                operator=st.operator_id,
                lat=st.lat, lon=st.lon,
                altitude=st.altitude_m,
                speed=st.speed_kt,
                heading=st.heading,
            )
            asyncio.run_coroutine_threadsafe(
                self.tracker.upsert(target),
                asyncio.get_event_loop(),
            )
