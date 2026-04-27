"""AIS via rtl_ais subprocess + NMEA TCP feed parser. Mirrors internal/ais/ais.go.

Spawns rtl_ais on the requested device, reads !AIVDM/!AIVDO sentences from its
TCP server (port 10110), decodes them with pyais, and produces unified Target
updates with vessel-specific fields populated.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from typing import Optional

from ..tracker import Target, Tracker, TYPE_VESSEL
from .lookups import (
    ship_type_str, nav_status_str, country_for_mmsi, format_mmsi, format_eta,
)

log = logging.getLogger("skywatch.ais")

_RTLAIS_TCP_PORT = 10110
_CONNECT_MAX = 30
_CONNECT_TIMEOUT = 2.0
_STATS_INTERVAL = 30.0


@dataclass
class AISConfig:
    rtl_ais_path: str = "rtl_ais"
    device_index: int = 1
    gain: float = 0.0
    external_host: str = ""  # "host:port" — connect instead of spawning


class AIS:
    def __init__(self, cfg: AISConfig, tracker: Tracker) -> None:
        self.cfg = cfg
        self.tracker = tracker
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._msgs = 0

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="ais-run")

    async def stop(self) -> None:
        self._stop.set()
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def _run(self) -> None:
        host, port = self._endpoint()
        if not self.cfg.external_host:
            try:
                await self._spawn_rtl_ais()
            except Exception as e:
                log.error("rtl_ais spawn failed: %s", e)
                return
        await self._consume(host, port)

    def _endpoint(self) -> tuple[str, int]:
        if self.cfg.external_host:
            host, _, port = self.cfg.external_host.partition(":")
            return host or "127.0.0.1", int(port or _RTLAIS_TCP_PORT)
        return "127.0.0.1", _RTLAIS_TCP_PORT

    async def _spawn_rtl_ais(self) -> None:
        binary = shutil.which(self.cfg.rtl_ais_path) or self.cfg.rtl_ais_path
        args = [binary, "-n", "-T", "-P", str(_RTLAIS_TCP_PORT), "-d", str(self.cfg.device_index)]
        if self.cfg.gain and self.cfg.gain > 0:
            args.extend(["-g", f"{int(self.cfg.gain)}"])
        log.info("starting rtl_ais: %s", " ".join(args))
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(2.0)
        if self._proc.returncode is not None:
            raise RuntimeError(f"rtl_ais exited rc={self._proc.returncode}")

    async def _consume(self, host: str, port: int) -> None:
        for attempt in range(1, _CONNECT_MAX + 1):
            if self._stop.is_set():
                return
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_CONNECT_TIMEOUT,
                )
                break
            except (OSError, asyncio.TimeoutError) as e:
                log.info("AIS connect %d/%d: %s", attempt, _CONNECT_MAX, e)
                await asyncio.sleep(1.0)
        else:
            log.error("AIS NMEA feed unreachable at %s:%d", host, port)
            return

        log.info("connected to AIS NMEA feed at %s:%d", host, port)
        try:
            from pyais.stream import IterMessages  # type: ignore
        except Exception as e:
            log.error("pyais missing/incompatible: %s", e)
            return

        last_stats = time.monotonic()
        try:
            buf = bytearray()
            while not self._stop.is_set():
                chunk = await reader.read(4096)
                if not chunk:
                    return
                buf.extend(chunk)
                while b"\n" in buf:
                    nl = buf.index(b"\n")
                    line = bytes(buf[:nl]).strip()
                    del buf[: nl + 1]
                    if not line.startswith(b"!AIV"):
                        continue
                    try:
                        for decoded in IterMessages([line]):
                            self._msgs += 1
                            await self._ingest(decoded.decode())
                    except Exception as e:
                        log.debug("AIS decode failed: %s", e)
                if (time.monotonic() - last_stats) >= _STATS_INTERVAL:
                    log.info("AIS stats: %d messages parsed", self._msgs)
                    last_stats = time.monotonic()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _ingest(self, msg) -> None:
        """Convert a pyais decoded message into a Target update."""
        # pyais returns a dataclass-like object with .asdict(); we use attrs directly.
        d = msg.asdict() if hasattr(msg, "asdict") else dict(msg)
        mmsi = d.get("mmsi")
        if not mmsi:
            return
        target = Target(id=f"MMSI-{format_mmsi(mmsi)}", type=TYPE_VESSEL, mmsi=format_mmsi(mmsi))
        target.country = country_for_mmsi(mmsi)
        if "lat" in d and "lon" in d and d["lat"] is not None and d["lon"] is not None:
            target.lat = float(d["lat"])
            target.lon = float(d["lon"])
        if "speed" in d and d["speed"] is not None:
            target.speed = float(d["speed"])
        if "course" in d and d["course"] is not None:
            target.heading = float(d["course"])
        if "heading" in d and d["heading"] is not None:
            h = float(d["heading"])
            if h < 360:
                target.heading = h
        if "shipname" in d and d["shipname"]:
            target.ship_name = str(d["shipname"]).rstrip(" @")
        if "callsign" in d and d["callsign"]:
            target.callsign = str(d["callsign"]).rstrip(" @")
        if "ship_type" in d and d["ship_type"] is not None:
            target.ship_type = int(d["ship_type"])
            target.ship_type_str = ship_type_str(target.ship_type)
        if "status" in d and d["status"] is not None:
            target.nav_status = nav_status_str(int(d["status"]))
        if "destination" in d and d["destination"]:
            target.destination = str(d["destination"]).rstrip(" @")
        if "draught" in d and d["draught"] is not None:
            target.draught = float(d["draught"])
        # Length/beam fields named to_bow/to_stern/to_port/to_starboard in AIS msg5.
        if all(k in d for k in ("to_bow", "to_stern")) and d["to_bow"] is not None and d["to_stern"] is not None:
            target.length = float(d["to_bow"]) + float(d["to_stern"])
        if all(k in d for k in ("to_port", "to_starboard")) and d["to_port"] is not None and d["to_starboard"] is not None:
            target.beam = float(d["to_port"]) + float(d["to_starboard"])
        if "imo" in d and d["imo"]:
            try:
                target.imo = int(d["imo"])
            except (TypeError, ValueError):
                pass
        if all(k in d for k in ("month", "day")) and d.get("month") and d.get("day"):
            target.eta = format_eta(int(d["month"]), int(d["day"]), int(d.get("hour", 0)), int(d.get("minute", 0)))

        await self.tracker.upsert(target)
