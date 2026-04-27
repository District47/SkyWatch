"""Geographic helpers shared by ADS-B and AIS bounding-box subscriptions."""
from __future__ import annotations

import math
from dataclasses import dataclass


# Default subscription center if not configured (geographic center of US).
DEFAULT_LAT = 39.8283
DEFAULT_LON = -98.5795
DEFAULT_RADIUS_KM = 500.0

KM_PER_DEG_LAT = 111.0


@dataclass
class Bounds:
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def to_json(self) -> dict:
        return {
            "min_lat": self.min_lat, "max_lat": self.max_lat,
            "min_lon": self.min_lon, "max_lon": self.max_lon,
        }


def radius_to_bounds(lat: float, lon: float, radius_km: float) -> Bounds:
    dlat = radius_km / KM_PER_DEG_LAT
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    dlon = radius_km / (KM_PER_DEG_LAT * cos_lat)
    return Bounds(lat - dlat, lat + dlat, lon - dlon, lon + dlon)


def clamp_box(b: Bounds, max_lat_span: float, max_lon_span: float) -> Bounds:
    """Clamp a bounding box to a maximum span (used by OpenSky)."""
    lat_mid = (b.min_lat + b.max_lat) / 2.0
    lon_mid = (b.min_lon + b.max_lon) / 2.0
    if (b.max_lat - b.min_lat) > max_lat_span:
        b.min_lat = lat_mid - max_lat_span / 2.0
        b.max_lat = lat_mid + max_lat_span / 2.0
    if (b.max_lon - b.min_lon) > max_lon_span:
        b.min_lon = lon_mid - max_lon_span / 2.0
        b.max_lon = lon_mid + max_lon_span / 2.0
    return b
