"""Best-effort vessel photo lookup via Wikipedia.

Hits the public REST `page/summary` endpoint, which returns a thumbnail of the
article's lead image when a page matches the ship's name. Most random tankers
and fishing boats won't have a Wikipedia article — that's expected. Famous
vessels (USS / RMS / cruise ships) typically return a hit.

Results are cached in-process so the same MMSI/name doesn't hit Wikipedia
repeatedly. Negative cache too, so we don't keep retrying misses.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("skywatch.ais.photos")

_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_USER_AGENT = "SkyWatch/1.0 (github.com/district47/skywatch)"
_TIMEOUT = 6.0


@dataclass
class PhotoResult:
    thumbnail: str = ""        # direct image URL (~320 px wide)
    page_url: str = ""         # Wikipedia article URL
    description: str = ""      # short article extract
    title: str = ""

    def to_json(self) -> dict:
        return self.__dict__


_cache: dict[str, PhotoResult] = {}
_cache_lock = asyncio.Lock()


def _normalise(name: str) -> str:
    # Strip AIS @-padding, collapse whitespace, title-case.
    n = re.sub(r"\s+", " ", (name or "").replace("@", " ")).strip()
    return n


async def _query_wikipedia(client: httpx.AsyncClient, title: str) -> Optional[PhotoResult]:
    url = _API.format(title=title.replace(" ", "_"))
    try:
        r = await client.get(url, follow_redirects=True)
    except Exception as e:
        log.debug("wikipedia summary fetch failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    thumb = (data.get("thumbnail") or {}).get("source") or ""
    page = (data.get("content_urls") or {}).get("desktop", {}).get("page") or ""
    if not thumb:
        return None
    return PhotoResult(
        thumbnail=thumb,
        page_url=page,
        description=data.get("extract", "")[:280],
        title=data.get("title", title),
    )


async def lookup_vessel_photo(name: str) -> PhotoResult:
    n = _normalise(name)
    if not n:
        return PhotoResult()
    async with _cache_lock:
        cached = _cache.get(n)
        if cached is not None:
            return cached
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as client:
        # Try the bare name, then a "<name> (ship)" disambiguation form which
        # Wikipedia commonly uses.
        result: Optional[PhotoResult] = await _query_wikipedia(client, n)
        if result is None:
            result = await _query_wikipedia(client, f"{n} (ship)")
    final = result or PhotoResult()
    async with _cache_lock:
        _cache[n] = final
    return final
