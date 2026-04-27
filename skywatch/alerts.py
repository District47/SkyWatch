"""Geofence alerts: fire an event when a target enters a defined zone.

Zones are circles (lat/lon center + radius_km). Each zone optionally filters
by target type (aircraft / vessel / drone) and aircraft category (military,
helicopter, mil-helo). Entry events are pushed over the existing WebSocket
broadcast and persisted in a small ring buffer.

State is persisted to data/alert_zones.json. Already-inside targets are
remembered per zone so we only alert on entry, not on every position update.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .tracker import Target, Tracker

log = logging.getLogger("skywatch.alerts")

_ZONES_FILE = Path("data/alert_zones.json")
_EVENT_RING = 100


@dataclass
class AlertZone:
    id: str
    name: str
    lat: float
    lon: float
    radius_km: float
    target_types: list[str] = field(default_factory=lambda: ["aircraft"])
    category_filter: str = ""  # "", "military", "helicopter", "mil-helo"
    callsign_filter: str = ""  # substring match on callsign / drone_id (case-insensitive)
    created_at: int = 0

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class AlertEvent:
    id: str
    zone_id: str
    zone_name: str
    target_id: str
    target_type: str
    callsign: str
    lat: float
    lon: float
    altitude: float
    speed: float
    heading: float
    timestamp: int

    def to_json(self) -> dict:
        return asdict(self)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points (km)."""
    R = 6371.0
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


class AlertManager:
    def __init__(self, tracker: Tracker, zones_path: Path = _ZONES_FILE) -> None:
        self.tracker = tracker
        self.zones_path = zones_path
        self._lock = asyncio.Lock()
        self._zones: dict[str, AlertZone] = {}
        # (zone_id, target_id) pairs currently inside, so we only alert on entry.
        self._inside: set[tuple[str, str]] = set()
        self._events: deque[AlertEvent] = deque(maxlen=_EVENT_RING)
        self._on_event: Optional[callable] = None
        self._load()
        tracker.add_observer(self._on_target)

    def set_event_callback(self, cb) -> None:
        self._on_event = cb

    def _load(self) -> None:
        if not self.zones_path.exists():
            return
        try:
            raw = json.loads(self.zones_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("alert zones load failed: %s", e)
            return
        for entry in raw:
            try:
                zone = AlertZone(**entry)
                self._zones[zone.id] = zone
            except Exception:
                continue
        log.info("loaded %d alert zone(s)", len(self._zones))

    def _save(self) -> None:
        self.zones_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.zones_path.with_suffix(".tmp")
        tmp.write_text(json.dumps([z.to_json() for z in self._zones.values()]), encoding="utf-8")
        tmp.replace(self.zones_path)

    async def list_zones(self) -> list[AlertZone]:
        async with self._lock:
            return list(self._zones.values())

    async def add_zone(self, *, name: str, lat: float, lon: float, radius_km: float,
                       target_types: Optional[list[str]] = None,
                       category_filter: str = "",
                       callsign_filter: str = "") -> AlertZone:
        zone = AlertZone(
            id=uuid.uuid4().hex[:12],
            name=name or "Unnamed zone",
            lat=float(lat), lon=float(lon), radius_km=float(radius_km),
            target_types=list(target_types or ["aircraft"]),
            category_filter=category_filter or "",
            callsign_filter=callsign_filter or "",
            created_at=int(time.time()),
        )
        async with self._lock:
            self._zones[zone.id] = zone
            self._save()
        return zone

    async def remove_zone(self, zone_id: str) -> bool:
        async with self._lock:
            if zone_id not in self._zones:
                return False
            del self._zones[zone_id]
            # Drop any "inside" tracking for this zone.
            self._inside = {pair for pair in self._inside if pair[0] != zone_id}
            self._save()
        return True

    async def events(self) -> list[AlertEvent]:
        async with self._lock:
            return list(self._events)

    def _matches(self, zone: AlertZone, t: Target) -> bool:
        if zone.target_types and t.type not in zone.target_types:
            return False
        if zone.category_filter and t.category != zone.category_filter:
            return False
        if zone.callsign_filter:
            needle = zone.callsign_filter.lower()
            haystack = (t.callsign or t.drone_id or "").lower()
            if needle not in haystack:
                return False
        return True

    async def _on_target(self, t: Target) -> None:
        if not t.lat and not t.lon:
            return
        if not self._zones:
            return
        async with self._lock:
            zones = list(self._zones.values())
            triggered: list[AlertEvent] = []
            for z in zones:
                if not self._matches(z, t):
                    continue
                d = haversine_km(z.lat, z.lon, t.lat, t.lon)
                key = (z.id, t.id)
                if d <= z.radius_km:
                    if key not in self._inside:
                        self._inside.add(key)
                        ev = AlertEvent(
                            id=uuid.uuid4().hex[:12],
                            zone_id=z.id, zone_name=z.name,
                            target_id=t.id, target_type=t.type,
                            callsign=t.callsign or t.drone_id or t.ship_name or "",
                            lat=t.lat, lon=t.lon,
                            altitude=t.altitude, speed=t.speed, heading=t.heading,
                            timestamp=int(time.time()),
                        )
                        self._events.append(ev)
                        triggered.append(ev)
                else:
                    self._inside.discard(key)
        for ev in triggered:
            log.info("ALERT: %s entered zone %s (%s)", ev.callsign or ev.target_id, ev.zone_name, ev.zone_id)
            if self._on_event:
                try:
                    self._on_event(ev)
                except Exception:
                    pass
