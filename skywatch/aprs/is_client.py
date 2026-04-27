"""APRS-IS internet gateway client. Mirrors internal/aprs/is.go.

Connects to an APRS-IS server (rotate.aprs2.net by default), authenticates,
applies a radius filter, and forwards packets into the parser/store. Also
exposes a send() method so the dashboard can transmit beacons / messages.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from .parser import parse_aprs_packet
from .store import APRSStore, APRSStation, APRSMessage
from .tx import compute_passcode

log = logging.getLogger("skywatch.aprs.is")


@dataclass
class APRSISConfig:
    server: str = "rotate.aprs2.net"
    port: int = 14580  # filtered TX-capable port
    callsign: str = "N0CALL"
    ssid: int = 0
    passcode: int = -1  # -1 = receive-only
    filter_lat: float = 0.0
    filter_lon: float = 0.0
    filter_radius_km: int = 150


class APRSISClient:
    def __init__(self, cfg: APRSISConfig, store: APRSStore) -> None:
        self.cfg = cfg
        self.store = store
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="aprs-is-run")

    async def stop(self) -> None:
        self._stop.set()
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def send(self, tnc2_line: str) -> bool:
        """Transmit a TNC2-formatted line (must already include CRLF? we add it)."""
        async with self._lock:
            if not self._writer:
                return False
            try:
                self._writer.write((tnc2_line.rstrip("\r\n") + "\r\n").encode("utf-8"))
                await self._writer.drain()
                return True
            except Exception as e:
                log.warning("APRS-IS send failed: %s", e)
                return False

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._connect_and_serve()
            except Exception as e:
                if self._stop.is_set():
                    return
                log.warning("APRS-IS connection error: %s; reconnecting in 5s", e)
                await asyncio.sleep(5.0)

    async def _connect_and_serve(self) -> None:
        log.info("APRS-IS connecting to %s:%d", self.cfg.server, self.cfg.port)
        reader, writer = await asyncio.open_connection(self.cfg.server, self.cfg.port)
        self._writer = writer
        try:
            # Login line: user CALL pass PASSCODE vers SkyWatch 1.0 filter r/lat/lon/km
            cs = self.cfg.callsign.upper()
            if self.cfg.ssid and 0 < self.cfg.ssid <= 15:
                cs = f"{cs}-{self.cfg.ssid}"
            passcode = self.cfg.passcode
            if passcode is None or passcode < 0:
                passcode = -1  # explicit receive-only
            login = f"user {cs} pass {passcode} vers SkyWatch 1.0"
            if self.cfg.filter_lat or self.cfg.filter_lon:
                login += f" filter r/{self.cfg.filter_lat:.4f}/{self.cfg.filter_lon:.4f}/{self.cfg.filter_radius_km}"
            writer.write((login + "\r\n").encode("utf-8"))
            await writer.drain()
            log.info("APRS-IS login: %s", login)
            while not self._stop.is_set():
                line = await reader.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if not text or text.startswith("#"):
                    continue
                await self._handle_packet(text)
        finally:
            self._writer = None
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_packet(self, raw: str) -> None:
        p = parse_aprs_packet(raw)
        if not p:
            return
        if p.data_type == ":" and p.msg_text:
            await self.store.add_message(APRSMessage(
                from_call=p.src_call, to_call=p.msg_dest,
                text=p.msg_text, msg_id=p.msg_id,
            ))
            return
        st = APRSStation(
            callsign=p.src_call,
            lat=p.lat, lon=p.lon,
            symbol=(p.symbol_table + p.symbol_code) if p.symbol_code else "",
            comment=p.comment,
            course=p.course, speed=p.speed, altitude=p.altitude,
            last_packet=raw, source="IS",
        )
        await self.store.upsert(st)
