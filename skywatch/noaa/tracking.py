"""NOAA satellite tracker via TLE + SGP4. Mirrors internal/noaa/tracking.go.

Pulls TLE elements from Celestrak every 6 hours and computes look angles for
the configured ground station. Returns predicted passes (next 24 h) plus live
positions for the dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sgp4.api import Satrec, jday

log = logging.getLogger("skywatch.noaa.tracking")

_CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=noaa&FORMAT=tle"
_TLE_REFRESH_HOURS = 6
_PREDICT_HOURS = 24
_PREDICT_REFRESH_SEC = 30 * 60  # 30 min
_EARTH_RADIUS_KM = 6371.0


NOAA_SATELLITES = [
    {"name": "NOAA 15", "norad_id": 25338, "frequency_mhz": 137.6200},
    {"name": "NOAA 18", "norad_id": 28654, "frequency_mhz": 137.9125},
    {"name": "NOAA 19", "norad_id": 33591, "frequency_mhz": 137.1000},
]


@dataclass
class SatPosition:
    name: str
    norad_id: int
    frequency_mhz: float
    lat: float
    lon: float
    altitude_km: float
    elevation_deg: float
    azimuth_deg: float
    visible: bool

    def to_json(self) -> dict:
        return self.__dict__


@dataclass
class SatellitePass:
    name: str
    norad_id: int
    frequency_mhz: float
    aos: str  # ISO timestamp
    los: str
    max_elevation: float
    direction: str  # "Northbound" / "Southbound"

    def to_json(self) -> dict:
        return self.__dict__


def _gmst(jd_ut1: float) -> float:
    """Greenwich Mean Sidereal Time (radians) — IAU 1982 approximation."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600 + 8640184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    rad = math.radians((gmst_sec % 86400.0) / 240.0)
    return rad % (2 * math.pi)


def _eci_to_geodetic(x: float, y: float, z: float, jd: float, fr: float) -> tuple[float, float, float]:
    gmst = _gmst(jd + fr)
    r = math.sqrt(x * x + y * y)
    lon = math.atan2(y, x) - gmst
    lat = math.atan2(z, r)
    alt = math.sqrt(x * x + y * y + z * z) - _EARTH_RADIUS_KM
    lon = ((lon + math.pi) % (2 * math.pi)) - math.pi
    return math.degrees(lat), math.degrees(lon), alt


def _look_angle(obs_lat: float, obs_lon: float, sat_lat: float, sat_lon: float, sat_alt_km: float) -> tuple[float, float]:
    """Approximate elevation + azimuth from observer to sub-satellite point."""
    lat1 = math.radians(obs_lat)
    lat2 = math.radians(sat_lat)
    dlon = math.radians(sat_lon - obs_lon)
    cos_c = math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(lat2) * math.cos(dlon)
    cos_c = max(-1.0, min(1.0, cos_c))
    c = math.acos(cos_c)  # central angle (radians)
    surface_dist_km = c * _EARTH_RADIUS_KM
    # Slant range (planar, good approximation for LEO).
    slant = math.sqrt(surface_dist_km ** 2 + sat_alt_km ** 2)
    elev = math.degrees(math.atan2(sat_alt_km - 0, surface_dist_km) - 0.0)
    # Use a stricter computation: el = atan2(alt - obs*cos(c), R*sin(c))
    if c == 0:
        elev = 90.0
    else:
        elev = math.degrees(math.atan2(
            math.cos(c) - (_EARTH_RADIUS_KM / (_EARTH_RADIUS_KM + sat_alt_km)),
            math.sin(c),
        ))
    # Azimuth from observer to sub-satellite point.
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    az = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return elev, az


@dataclass
class _Sat:
    name: str
    norad_id: int
    frequency_mhz: float
    rec: Satrec


class NOAATracker:
    def __init__(self, observer_lat: float = 0.0, observer_lon: float = 0.0) -> None:
        self.obs_lat = observer_lat
        self.obs_lon = observer_lon
        self._sats: list[_Sat] = []
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._passes: list[SatellitePass] = []

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="noaa-tracker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()

    def set_observer(self, lat: float, lon: float) -> None:
        self.obs_lat = lat
        self.obs_lon = lon

    async def _run(self) -> None:
        await self._refresh_tles()
        last_tle_refresh = asyncio.get_event_loop().time()
        await self._predict_passes()
        last_predict = asyncio.get_event_loop().time()
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60.0)
                if self._stop.is_set():
                    return
            except asyncio.TimeoutError:
                pass
            now = asyncio.get_event_loop().time()
            if (now - last_tle_refresh) >= _TLE_REFRESH_HOURS * 3600:
                await self._refresh_tles()
                last_tle_refresh = now
            if (now - last_predict) >= _PREDICT_REFRESH_SEC:
                await self._predict_passes()
                last_predict = now

    async def _refresh_tles(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(_CELESTRAK_URL)
                r.raise_for_status()
                tle_block = r.text
        except Exception as e:
            log.warning("TLE fetch failed: %s", e)
            return

        wanted = {s["norad_id"]: s for s in NOAA_SATELLITES}
        sats: list[_Sat] = []
        lines = [l.strip() for l in tle_block.splitlines() if l.strip()]
        for i in range(0, len(lines) - 2, 3):
            name = lines[i]
            l1 = lines[i + 1]
            l2 = lines[i + 2]
            if not (l1.startswith("1 ") and l2.startswith("2 ")):
                continue
            try:
                norad = int(l1[2:7])
            except ValueError:
                continue
            if norad not in wanted:
                continue
            try:
                rec = Satrec.twoline2rv(l1, l2)
            except Exception as e:
                log.exception(f"Failed operation: {e}")
                continue
            sats.append(_Sat(name=wanted[norad]["name"], norad_id=norad,
                             frequency_mhz=wanted[norad]["frequency_mhz"], rec=rec))
        if sats:
            self._sats = sats
            log.info("loaded %d NOAA TLEs", len(sats))

    def _propagate(self, sat: _Sat, when: datetime) -> Optional[SatPosition]:
        jd, fr = jday(when.year, when.month, when.day, when.hour, when.minute, when.second + when.microsecond / 1e6)
        e, r, _ = sat.rec.sgp4(jd, fr)
        if e != 0 or not r:
            return None
        lat, lon, alt = _eci_to_geodetic(r[0], r[1], r[2], jd, fr)
        elev, az = _look_angle(self.obs_lat, self.obs_lon, lat, lon, alt)
        return SatPosition(
            name=sat.name, norad_id=sat.norad_id, frequency_mhz=sat.frequency_mhz,
            lat=lat, lon=lon, altitude_km=alt,
            elevation_deg=elev, azimuth_deg=az, visible=elev > 0,
        )

    def positions(self) -> list[SatPosition]:
        now = datetime.now(timezone.utc)
        out = []
        for sat in self._sats:
            p = self._propagate(sat, now)
            if p:
                out.append(p)
        return out

    async def _predict_passes(self) -> None:
        passes: list[SatellitePass] = []
        start = datetime.now(timezone.utc)
        end = start + timedelta(hours=_PREDICT_HOURS)
        step = timedelta(seconds=30)
        for sat in self._sats:
            t = start
            in_pass = False
            aos: Optional[datetime] = None
            max_elev = 0.0
            entry_lat = 0.0
            while t < end:
                p = self._propagate(sat, t)
                if not p:
                    t += step
                    continue
                if p.visible and not in_pass:
                    in_pass = True
                    aos = t
                    max_elev = p.elevation_deg
                    entry_lat = p.lat
                elif p.visible and in_pass:
                    if p.elevation_deg > max_elev:
                        max_elev = p.elevation_deg
                elif (not p.visible) and in_pass:
                    in_pass = False
                    direction = "Northbound" if p.lat > entry_lat else "Southbound"
                    passes.append(SatellitePass(
                        name=sat.name, norad_id=sat.norad_id, frequency_mhz=sat.frequency_mhz,
                        aos=aos.isoformat() if aos else "",
                        los=t.isoformat(),
                        max_elevation=max_elev, direction=direction,
                    ))
                    aos = None
                t += step
        passes.sort(key=lambda p: p.aos)
        self._passes = passes

    def passes(self) -> list[SatellitePass]:
        return list(self._passes)
