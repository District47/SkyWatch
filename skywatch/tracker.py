"""Unified in-memory store for all tracked targets (aircraft, vessels, drones).

Mirrors internal/tracker/tracker.go from the Go implementation. Thread-safe via
asyncio.Lock since updates arrive from many concurrent module tasks. Preserves
non-empty fields across updates so partial messages accumulate over time.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional


TYPE_AIRCRAFT = "aircraft"
TYPE_VESSEL = "vessel"
TYPE_DRONE = "drone"


@dataclass
class Target:
    id: str
    type: str
    callsign: str = ""
    lat: float = 0.0
    lon: float = 0.0
    altitude: float = 0.0
    speed: float = 0.0
    heading: float = 0.0
    last_seen: int = 0
    messages: int = 0

    # Aircraft
    squawk: str = ""
    registration: str = ""
    aircraft_type: str = ""
    typecode: str = ""
    owner: str = ""
    category: str = ""

    # Vessel
    mmsi: str = ""
    ship_name: str = ""
    ship_type: int = 0
    ship_type_str: str = ""
    nav_status: str = ""
    destination: str = ""
    eta: str = ""
    draught: float = 0.0
    length: float = 0.0
    beam: float = 0.0
    imo: int = 0
    country: str = ""

    # Drone
    drone_id: str = ""
    operator: str = ""

    def to_json(self) -> dict:
        d = asdict(self)
        # Drop empties to keep JSON small (Go uses omitempty).
        out = {}
        for k, v in d.items():
            if v == "" or v == 0 or v == 0.0:
                if k in ("id", "type", "last_seen"):
                    out[k] = v
                continue
            out[k] = v
        return out


def _merge(prev: Target, new: Target) -> Target:
    """Apply new onto prev, preserving non-empty prev fields when new is empty."""
    for k, v in asdict(new).items():
        if v in ("", 0, 0.0, None):
            continue
        setattr(prev, k, v)
    return prev


class Tracker:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._targets: dict[str, Target] = {}
        self._on_change: Optional[Callable[[], None]] = None

    def set_change_callback(self, cb: Callable[[], None]) -> None:
        self._on_change = cb

    async def upsert(self, t: Target) -> None:
        t.last_seen = int(time.time())
        async with self._lock:
            existing = self._targets.get(t.id)
            if existing is None:
                t.messages = max(t.messages, 1)
                self._targets[t.id] = t
            else:
                _merge(existing, t)
                existing.messages += 1
                existing.last_seen = t.last_seen
        if self._on_change:
            try:
                self._on_change()
            except Exception:
                pass

    async def snapshot(self) -> list[Target]:
        async with self._lock:
            return list(self._targets.values())

    async def prune(self, max_age_seconds: int = 300) -> int:
        cutoff = int(time.time()) - max_age_seconds
        removed = 0
        async with self._lock:
            for tid in list(self._targets.keys()):
                if self._targets[tid].last_seen < cutoff:
                    del self._targets[tid]
                    removed += 1
        if removed and self._on_change:
            try:
                self._on_change()
            except Exception:
                pass
        return removed

    async def counts(self) -> dict[str, int]:
        async with self._lock:
            counts: dict[str, int] = {}
            for t in self._targets.values():
                counts[t.type] = counts.get(t.type, 0) + 1
            return counts
