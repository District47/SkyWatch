"""api.weather.gov client. Mirrors the relevant subset of the Go weather endpoints."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

log = logging.getLogger("skywatch.noaa.weather_api")

_BASE = "https://api.weather.gov"
_USER_AGENT = "SkyWatch/1.0 (github.com/district47/skywatch)"
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/geo+json",
}
_TIMEOUT = 10.0


async def fetch_alerts(*, lat: Optional[float] = None, lon: Optional[float] = None,
                       state: str = "", wfo: str = "") -> list[dict]:
    params: dict[str, str] = {}
    if state:
        params["area"] = state.upper()
    elif wfo:
        params["zone"] = wfo.upper()
    elif lat is not None and lon is not None:
        params["point"] = f"{lat:.4f},{lon:.4f}"
    url = f"{_BASE}/alerts/active"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json().get("features", [])
    except Exception as e:
        log.warning("alerts fetch failed: %s", e)
        return []


async def fetch_forecast(lat: float, lon: float) -> list[dict]:
    """Two-step weather.gov lookup: /points/{lat},{lon} → forecast URL → periods."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            point = await client.get(f"{_BASE}/points/{lat:.4f},{lon:.4f}")
            point.raise_for_status()
            forecast_url = point.json().get("properties", {}).get("forecast")
            if not forecast_url:
                return []
            fc = await client.get(forecast_url)
            fc.raise_for_status()
            return fc.json().get("properties", {}).get("periods", [])
    except Exception as e:
        log.warning("forecast fetch failed: %s", e)
        return []
