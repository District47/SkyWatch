"""APRS station + message store. Mirrors internal/aprs/station.go."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


_PRUNE_AGE_SECONDS = 30 * 60  # 30 minutes
_MAX_MESSAGES = 200


@dataclass
class APRSStation:
    callsign: str
    lat: float = 0.0
    lon: float = 0.0
    symbol: str = ""
    comment: str = ""
    course: int = 0
    speed: float = 0.0
    altitude: int = 0
    last_packet: str = ""
    source: str = ""  # "IS", "RF", "UV-Pro"
    seen: int = 0
    messages: int = 0

    def to_json(self) -> dict:
        return {
            "callsign": self.callsign, "lat": self.lat, "lon": self.lon,
            "symbol": self.symbol, "comment": self.comment,
            "course": self.course, "speed": self.speed, "altitude": self.altitude,
            "last_packet": self.last_packet, "source": self.source,
            "seen": self.seen, "messages": self.messages,
        }


@dataclass
class APRSMessage:
    from_call: str
    to_call: str
    text: str
    msg_id: str = ""
    timestamp: int = 0

    def to_json(self) -> dict:
        return {
            "from": self.from_call, "to": self.to_call,
            "text": self.text, "id": self.msg_id, "timestamp": self.timestamp,
        }


class APRSStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._stations: dict[str, APRSStation] = {}
        self._messages: deque[APRSMessage] = deque(maxlen=_MAX_MESSAGES)

    async def upsert(self, station: APRSStation) -> None:
        station.seen = int(time.time())
        async with self._lock:
            existing = self._stations.get(station.callsign)
            if not existing:
                station.messages = max(station.messages, 1)
                self._stations[station.callsign] = station
            else:
                # Preserve non-empty fields.
                for k, v in station.__dict__.items():
                    if v in ("", 0, 0.0, None):
                        continue
                    setattr(existing, k, v)
                existing.messages += 1
                existing.seen = station.seen

    async def add_message(self, msg: APRSMessage) -> None:
        msg.timestamp = int(time.time())
        async with self._lock:
            self._messages.append(msg)

    async def stations(self) -> list[APRSStation]:
        async with self._lock:
            return list(self._stations.values())

    async def messages(self) -> list[APRSMessage]:
        async with self._lock:
            return list(self._messages)

    async def prune(self, max_age_seconds: int = _PRUNE_AGE_SECONDS) -> int:
        cutoff = int(time.time()) - max_age_seconds
        removed = 0
        async with self._lock:
            for cs in list(self._stations.keys()):
                if self._stations[cs].seen < cutoff:
                    del self._stations[cs]
                    removed += 1
        return removed
