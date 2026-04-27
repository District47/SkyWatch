"""OpenSky Network online ADS-B feed. Mirrors internal/adsb/opensky.go.

Polls the public REST endpoint at the free-tier rate limit (10s) and converts
state vectors into Target updates. Bounding box defaults to a window around
the geographic center of the US, clamped per the original Go limits.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from ..tracker import Target, Tracker, TYPE_AIRCRAFT
from ..util.geo import (
    Bounds, DEFAULT_LAT, DEFAULT_LON, DEFAULT_RADIUS_KM,
    radius_to_bounds, clamp_box,
)
from .aircraft_db import AircraftDB
from .classify import classify

log = logging.getLogger("skywatch.adsb.opensky")

_OPENSKY_URL = "https://opensky-network.org/api/states/all"
_POLL_INTERVAL = 10.0
_HTTP_TIMEOUT = 15.0
_USER_AGENT = "SkyWatch/1.0"
_MAX_LAT_SPAN = 20.0
_MAX_LON_SPAN = 30.0
_M_TO_FT = 3.28084
_MS_TO_KT = 1.94384


@dataclass
class OpenSkyConfig:
    enabled: bool = False
    center_lat: float = DEFAULT_LAT
    center_lon: float = DEFAULT_LON
    radius_km: float = DEFAULT_RADIUS_KM
    db: Optional[AircraftDB] = None


class OpenSky:
    def __init__(self, cfg: OpenSkyConfig, tracker: Tracker) -> None:
        self.cfg = cfg
        self.tracker = tracker
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._box: Optional[Bounds] = None  # explicit box from the dashboard takes priority
        self._bounds_set = asyncio.Event()  # don't poll until the dashboard has told us where to look

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="adsb-opensky")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    def set_bounds(self, lat: float, lon: float, radius_km: float) -> None:
        self.cfg.center_lat = lat
        self.cfg.center_lon = lon
        self.cfg.radius_km = radius_km
        self._box = None
        self._bounds_set.set()

    def set_box(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> None:
        self._box = Bounds(min_lat=min_lat, max_lat=max_lat, min_lon=min_lon, max_lon=max_lon)
        self._bounds_set.set()

    async def _run(self) -> None:
        # Wait for the dashboard to push its current view before the first poll —
        # otherwise we'd briefly fetch the default (center-US) box and stick
        # those aircraft on the map until the user pans.
        log.info("opensky idle until first bounds update from dashboard")
        try:
            await asyncio.wait_for(self._bounds_set.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            log.info("opensky proceeding with default bounds (no dashboard bounds in 10s)")

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
            while not self._stop.is_set():
                try:
                    await self._poll(client)
                except Exception as e:
                    log.warning("opensky poll failed: %s", e)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=_POLL_INTERVAL)
                except asyncio.TimeoutError:
                    pass

    async def _poll(self, client: httpx.AsyncClient) -> None:
        if self._box is not None:
            b = Bounds(self._box.min_lat, self._box.max_lat, self._box.min_lon, self._box.max_lon)
        else:
            b = radius_to_bounds(self.cfg.center_lat, self.cfg.center_lon, self.cfg.radius_km)
        b = clamp_box(b, _MAX_LAT_SPAN, _MAX_LON_SPAN)
        params = {
            "lamin": f"{b.min_lat:.4f}", "lamax": f"{b.max_lat:.4f}",
            "lomin": f"{b.min_lon:.4f}", "lomax": f"{b.max_lon:.4f}",
        }
        r = await client.get(_OPENSKY_URL, params=params)
        if r.status_code != 200:
            log.info("opensky returned %d", r.status_code)
            return
        data = r.json()
        states = data.get("states") or []
        for s in states:
            await self._ingest(s)

    async def _ingest(self, s: list) -> None:
        # OpenSky state vector index reference (https://openskynetwork.github.io/opensky-api/rest.html).
        try:
            icao = (s[0] or "").strip().upper()
            if not icao:
                return
            callsign = (s[1] or "").strip()
            lon = s[5]
            lat = s[6]
            if lon is None or lat is None:
                return
            baro_alt_m = s[7]
            velocity_ms = s[9]
            heading = s[10] or 0.0
            squawk = (s[14] or "")
        except (IndexError, ValueError, TypeError):
            return

        target = Target(
            id=f"ICAO-{icao}",
            type=TYPE_AIRCRAFT,
            callsign=callsign,
            lat=float(lat), lon=float(lon),
            altitude=(float(baro_alt_m) * _M_TO_FT) if baro_alt_m is not None else 0.0,
            speed=(float(velocity_ms) * _MS_TO_KT) if velocity_ms is not None else 0.0,
            heading=float(heading) if heading is not None else 0.0,
            squawk=str(squawk) if squawk else "",
        )
        if self.cfg.db:
            info = self.cfg.db.lookup(icao)
            if info:
                target.registration = info.registration
                target.aircraft_type = info.type
                target.typecode = info.typecode
                target.owner = info.owner or info.operator
                target.category = classify(icao, info.typecode, info.operator, info.owner, info.type)
        await self.tracker.upsert(target)
