"""aisstream.io WebSocket subscriber. Mirrors internal/ais/aisstream.go.

Connects to wss://stream.aisstream.io/v0/stream and subscribes to the user's
bounding box. Re-subscription is rate-limited and ignored for tiny pans (per
the Go implementation: 3s minimum between resubs, 0.5° significance threshold).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

import websockets

from ..tracker import Target, Tracker, TYPE_VESSEL
from ..util.geo import (
    Bounds, DEFAULT_LAT, DEFAULT_LON, DEFAULT_RADIUS_KM, radius_to_bounds,
)
from .lookups import (
    ship_type_str, nav_status_str, country_for_mmsi, format_mmsi, format_eta,
)

log = logging.getLogger("skywatch.ais.aisstream")

_WS_URL = "wss://stream.aisstream.io/v0/stream"
_RECONNECT_DELAY = 5.0
_RESUB_RATE_LIMIT = 3.0
_SIGNIFICANT_DEGREES = 0.5
_MIN_RADIUS_DEG = 2.0
_MSG_TYPES = ["PositionReport", "ShipStaticData", "StandardClassBPositionReport"]


@dataclass
class AISStreamConfig:
    api_key: str = ""
    center_lat: float = DEFAULT_LAT
    center_lon: float = DEFAULT_LON
    radius_km: float = DEFAULT_RADIUS_KM


class AISStream:
    def __init__(self, cfg: AISStreamConfig, tracker: Tracker) -> None:
        self.cfg = cfg
        self.tracker = tracker
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._last_resub: float = 0.0
        self._last_box: Optional[Bounds] = None
        self._explicit_box: Optional[Bounds] = None

    async def start(self) -> None:
        if not self.cfg.api_key:
            log.info("aisstream disabled (no API key)")
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="aisstream-run")

    async def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                log.exception(f"Failed to stop web socket: {e}")
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def set_bounds(self, lat: float, lon: float, radius_km: float) -> None:
        self.cfg.center_lat = lat
        self.cfg.center_lon = lon
        self.cfg.radius_km = radius_km
        self._explicit_box = None
        await self._maybe_resubscribe(force=False)

    async def set_box(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> None:
        self._explicit_box = Bounds(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
        await self._maybe_resubscribe(force=False)

    async def _maybe_resubscribe(self, force: bool) -> None:
        if not self._ws:
            return
        now = time.monotonic()
        if not force and (now - self._last_resub) < _RESUB_RATE_LIMIT:
            return
        new_box = self._compute_box()
        if not force and self._last_box and not self._significantly_different(new_box, self._last_box):
            return
        try:
            await self._ws.send(json.dumps(self._sub_message(new_box)))
            self._last_resub = now
            self._last_box = new_box
        except Exception as e:
            log.warning("aisstream resubscribe failed: %s", e)

    def _compute_box(self) -> Bounds:
        if self._explicit_box is not None:
            return Bounds(self._explicit_box.min_lat, self._explicit_box.max_lat,
                          self._explicit_box.min_lon, self._explicit_box.max_lon)
        b = radius_to_bounds(self.cfg.center_lat, self.cfg.center_lon, self.cfg.radius_km)
        # Enforce minimum radius (in degrees) so we don't spam tiny boxes.
        if (b.max_lat - b.min_lat) < _MIN_RADIUS_DEG:
            mid = (b.max_lat + b.min_lat) / 2.0
            b.min_lat = mid - _MIN_RADIUS_DEG / 2.0
            b.max_lat = mid + _MIN_RADIUS_DEG / 2.0
        if (b.max_lon - b.min_lon) < _MIN_RADIUS_DEG:
            mid = (b.max_lon + b.min_lon) / 2.0
            b.min_lon = mid - _MIN_RADIUS_DEG / 2.0
            b.max_lon = mid + _MIN_RADIUS_DEG / 2.0
        return b

    def _significantly_different(self, a: Bounds, b: Bounds) -> bool:
        return (
            abs(a.min_lat - b.min_lat) >= _SIGNIFICANT_DEGREES or
            abs(a.max_lat - b.max_lat) >= _SIGNIFICANT_DEGREES or
            abs(a.min_lon - b.min_lon) >= _SIGNIFICANT_DEGREES or
            abs(a.max_lon - b.max_lon) >= _SIGNIFICANT_DEGREES
        )

    def _sub_message(self, b: Bounds) -> dict:
        return {
            "APIKey": self.cfg.api_key,
            "BoundingBoxes": [[[b.min_lat, b.min_lon], [b.max_lat, b.max_lon]]],
            "FilterMessageTypes": _MSG_TYPES,
        }

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with websockets.connect(_WS_URL, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    box = self._compute_box()
                    await ws.send(json.dumps(self._sub_message(box)))
                    self._last_resub = time.monotonic()
                    self._last_box = box
                    log.info("aisstream subscribed (lat %.2f..%.2f lon %.2f..%.2f)",
                             box.min_lat, box.max_lat, box.min_lon, box.max_lon)
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                        except Exception as e:
                            log.exception(f"Failed to load aisstream json: {e}")
                            continue
                        await self._ingest(msg)
            except Exception as e:
                if self._stop.is_set():
                    return
                log.warning("aisstream connection error: %s; reconnecting in %.0fs", e, _RECONNECT_DELAY)
                await asyncio.sleep(_RECONNECT_DELAY)
            finally:
                self._ws = None

    async def _ingest(self, msg: dict) -> None:
        meta = msg.get("MetaData") or {}
        mmsi = meta.get("MMSI") or msg.get("MMSI")
        if not mmsi:
            return
        msg_type = msg.get("MessageType") or ""
        target = Target(id=f"MMSI-{format_mmsi(mmsi)}", type=TYPE_VESSEL, mmsi=format_mmsi(mmsi))
        target.country = country_for_mmsi(mmsi)
        ship_name = (meta.get("ShipName") or "").strip()
        if ship_name:
            target.ship_name = ship_name.rstrip(" @")

        if msg_type == "PositionReport":
            inner = msg.get("Message", {}).get("PositionReport", {})
            target.lat = float(inner.get("Latitude") or 0.0)
            target.lon = float(inner.get("Longitude") or 0.0)
            target.speed = float(inner.get("Sog") or 0.0)
            cog = inner.get("Cog")
            hdg = inner.get("TrueHeading")
            if hdg is not None and hdg < 360:
                target.heading = float(hdg)
            elif cog is not None:
                target.heading = float(cog)
            ns = inner.get("NavigationalStatus")
            if ns is not None:
                target.nav_status = nav_status_str(int(ns))
        elif msg_type == "StandardClassBPositionReport":
            inner = msg.get("Message", {}).get("StandardClassBPositionReport", {})
            target.lat = float(inner.get("Latitude") or 0.0)
            target.lon = float(inner.get("Longitude") or 0.0)
            target.speed = float(inner.get("Sog") or 0.0)
            target.heading = float(inner.get("Cog") or 0.0)
        elif msg_type == "ShipStaticData":
            inner = msg.get("Message", {}).get("ShipStaticData", {})
            cs = (inner.get("CallSign") or "").strip()
            if cs:
                target.callsign = cs.rstrip(" @")
            st = inner.get("Type")
            if st is not None:
                target.ship_type = int(st)
                target.ship_type_str = ship_type_str(target.ship_type)
            dest = (inner.get("Destination") or "").strip()
            if dest:
                target.destination = dest.rstrip(" @")
            d = inner.get("MaximumStaticDraught")
            if d is not None:
                target.draught = float(d)
            dim = inner.get("Dimension") or {}
            a, b = dim.get("A"), dim.get("B")
            if a is not None and b is not None:
                target.length = float(a) + float(b)
            c, dc = dim.get("C"), dim.get("D")
            if c is not None and dc is not None:
                target.beam = float(c) + float(dc)
            imo = inner.get("ImoNumber")
            if imo:
                try:
                    target.imo = int(imo)
                except (TypeError, ValueError):
                    pass
            eta = inner.get("Eta") or {}
            if eta.get("Month") and eta.get("Day"):
                target.eta = format_eta(
                    int(eta.get("Month")), int(eta.get("Day")),
                    int(eta.get("Hour") or 0), int(eta.get("Minute") or 0),
                )
        else:
            return

        await self.tracker.upsert(target)
