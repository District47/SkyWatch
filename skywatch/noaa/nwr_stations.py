"""NWR transmitter database. Loads data/nwr_stations.csv (copied from Go project)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class NWRTransmitter:
    callsign: str
    frequency_mhz: float
    lat: float
    lon: float
    name: str
    location: str
    state: str
    power_watts: float
    wfo: str
    status: str

    def to_json(self) -> dict:
        return asdict(self)


def load_stations(csv_path: Path = Path("data/nwr_stations.csv")) -> list[NWRTransmitter]:
    if not csv_path.exists():
        return []
    out: list[NWRTransmitter] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) < 10:
                continue
            try:
                freq = float(row[1]) if row[1] else 0.0
                lat = float(row[2]) if row[2] else 0.0
                lon = float(row[3]) if row[3] else 0.0
                power = float(row[7]) if row[7] else 0.0
            except ValueError:
                continue
            out.append(NWRTransmitter(
                callsign=row[0], frequency_mhz=freq, lat=lat, lon=lon,
                name=row[4], location=row[5], state=row[6],
                power_watts=power, wfo=row[8], status=row[9],
            ))
    return out


NWR_TRANSMITTERS: list[NWRTransmitter] = load_stations()
