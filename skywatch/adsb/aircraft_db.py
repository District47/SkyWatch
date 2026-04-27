"""Aircraft metadata DB (cached locally; importable from OpenSky CSV).

Mirrors internal/adsb/aircraftdb.go.
"""
from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import httpx


_OPENSKY_CSV_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
_DEFAULT_CACHE = Path("data/aircraft.json")


@dataclass
class AircraftInfo:
    registration: str = ""
    type: str = ""
    typecode: str = ""
    operator: str = ""
    owner: str = ""
    category: str = ""

    def to_json(self) -> dict:
        return asdict(self)


class AircraftDB:
    def __init__(self, cache_path: Path = _DEFAULT_CACHE) -> None:
        self.cache_path = cache_path
        self._db: dict[str, AircraftInfo] = {}
        self.load()

    def load(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            with self.cache_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            self._db = {k.upper(): AircraftInfo(**v) for k, v in raw.items()}
        except Exception:
            self._db = {}

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self._db.items()}, f)
        tmp.replace(self.cache_path)

    def lookup(self, icao_hex: str) -> Optional[AircraftInfo]:
        return self._db.get(icao_hex.upper())

    def count(self) -> int:
        return len(self._db)

    async def import_from_opensky(self) -> int:
        """Download the OpenSky aircraft DB CSV and import every usable record."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            r = await client.get(_OPENSKY_CSV_URL, follow_redirects=True)
            r.raise_for_status()
            text = r.text
        return self.import_csv(text)

    def import_csv(self, text: str) -> int:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return 0
        idx = {name.strip("'\""): i for i, name in enumerate(header)}
        required = ["icao24", "registration", "manufacturername", "model", "typecode", "operator", "owner"]
        if not all(c in idx for c in required):
            return 0
        added = 0
        for row in reader:
            try:
                icao = row[idx["icao24"]].strip().upper()
                if not icao:
                    continue
                reg = row[idx["registration"]].strip()
                mfr = row[idx["manufacturername"]].strip()
                model = row[idx["model"]].strip()
                tc = row[idx["typecode"]].strip()
                op = row[idx["operator"]].strip()
                owner = row[idx["owner"]].strip()
                full_type = (mfr + " " + model).strip()
                if not (reg or full_type or tc or op or owner):
                    continue
                self._db[icao] = AircraftInfo(
                    registration=reg, type=full_type, typecode=tc,
                    operator=op, owner=owner, category="",
                )
                added += 1
            except (IndexError, ValueError):
                continue
        self.save()
        return added
