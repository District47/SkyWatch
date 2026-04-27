"""ADS-B via readsb subprocess + SBS (BaseStation) TCP feed parser.

Mirrors internal/adsb/adsb.go. Spawns the `readsb` binary on the requested
RTL-SDR device, then parses its SBS output (TCP port 30003 by default) into
unified Target updates.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import time
from dataclasses import dataclass, field
from typing import Optional

from ..tracker import Target, Tracker, TYPE_AIRCRAFT
from .aircraft_db import AircraftDB
from .classify import classify

log = logging.getLogger("skywatch.adsb")

# 1090 MHz, ADS-B center frequency; SBS TCP output port.
_ADSB_FREQ_HZ = 1_090_000_000
_SBS_PORT = 30003

# Spawn retry budget — readsb sometimes fails on first device claim.
_READSB_MAX_ATTEMPTS = 10
_SBS_CONNECT_MAX = 30
_SBS_CONNECT_TIMEOUT = 2.0
_STATS_INTERVAL = 10.0


@dataclass
class ADSBConfig:
    readsb_path: str = "readsb"
    device_index: int = 0
    gain: float = 0.0  # dB; 0 = auto
    external_host: str = ""  # "host:port"; if set, skip spawning readsb
    db: Optional[AircraftDB] = None


class ADSB:
    """Manages a readsb subprocess and parses its SBS feed into the tracker."""

    def __init__(self, cfg: ADSBConfig, tracker: Tracker) -> None:
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
        self._task = asyncio.create_task(self._run(), name="adsb-run")

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
        try:
            host, port = self._target_endpoint()
            if not self.cfg.external_host:
                await self._spawn_readsb()
            await self._consume_sbs(host, port)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("adsb pipeline failed: %s", e)

    def _target_endpoint(self) -> tuple[str, int]:
        if self.cfg.external_host:
            host, _, port = self.cfg.external_host.partition(":")
            return host or "127.0.0.1", int(port or _SBS_PORT)
        return "127.0.0.1", _SBS_PORT

    async def _spawn_readsb(self) -> None:
        binary = shutil.which(self.cfg.readsb_path) or self.cfg.readsb_path
        gain_args = []
        if self.cfg.gain and self.cfg.gain > 0:
            gain_args = ["--gain", f"{self.cfg.gain:g}"]
        args = [
            binary,
            "--device-type", "rtlsdr",
            "--device", str(self.cfg.device_index),
            "--freq", str(_ADSB_FREQ_HZ),
            "--net",
            "--net-sbs-port", str(_SBS_PORT),
            "--net-ri-port", "0",
            "--net-ro-port", "0",
            "--net-bi-port", "0",
            "--net-bo-port", "0",
            "--net-api-port", "0",
            "--quiet",
            *gain_args,
        ]
        env = os.environ.copy()
        # RTL-SDR Blog V4 fallback library path on macOS.
        blog_lib = os.environ.get("RTLSDR_LIB_PATH") or "/tmp/rtl-sdr-blog/build/src/librtlsdr.0.dylib"
        if os.path.exists(blog_lib):
            env["DYLD_LIBRARY_PATH"] = os.path.dirname(blog_lib) + ":" + env.get("DYLD_LIBRARY_PATH", "")

        last_err: Optional[Exception] = None
        for attempt in range(1, _READSB_MAX_ATTEMPTS + 1):
            if self._stop.is_set():
                return
            log.info("starting readsb (attempt %d): %s", attempt, " ".join(shlex.quote(a) for a in args))
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
            except FileNotFoundError as e:
                raise RuntimeError(f"readsb binary not found at {binary!r}") from e
            # Give readsb 3s to claim the device.
            await asyncio.sleep(3.0)
            if self._proc.returncode is None:
                return
            stderr = (await self._proc.stderr.read()).decode("utf-8", errors="replace") if self._proc.stderr else ""
            last_err = RuntimeError(f"readsb exited rc={self._proc.returncode}: {stderr.strip()[:300]}")
            log.warning("%s (retrying in %ds)", last_err, 2 + attempt)
            await asyncio.sleep(2 + attempt)
        raise last_err or RuntimeError("readsb failed to start")

    async def _consume_sbs(self, host: str, port: int) -> None:
        last_stats = time.monotonic()
        for attempt in range(1, _SBS_CONNECT_MAX + 1):
            if self._stop.is_set():
                return
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_SBS_CONNECT_TIMEOUT,
                )
                break
            except (OSError, asyncio.TimeoutError) as e:
                log.info("SBS connect %d/%d to %s:%d failed: %s", attempt, _SBS_CONNECT_MAX, host, port, e)
                await asyncio.sleep(1.0)
        else:
            log.error("could not connect to SBS feed %s:%d", host, port)
            return

        log.info("connected to SBS feed at %s:%d", host, port)
        try:
            while not self._stop.is_set():
                line = await reader.readline()
                if not line:
                    log.warning("SBS feed closed by peer")
                    return
                self._msgs += 1
                try:
                    self._handle_line(line.decode("utf-8", errors="replace").strip())
                except Exception as e:
                    log.debug("malformed SBS line: %s (%s)", line[:80], e)
                if (time.monotonic() - last_stats) >= _STATS_INTERVAL:
                    log.info("ADS-B stats: %d messages parsed", self._msgs)
                    last_stats = time.monotonic()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _handle_line(self, line: str) -> None:
        # SBS format: comma-separated, fields per BaseStation spec.
        if not line.startswith("MSG,"):
            return
        f = line.split(",")
        if len(f) < 22:
            return
        icao = f[4].strip().upper()
        if not icao:
            return

        target = Target(id=f"ICAO-{icao}", type=TYPE_AIRCRAFT)

        callsign = f[10].strip()
        if callsign:
            target.callsign = callsign
        try:
            if f[11]:
                target.altitude = float(f[11])
            if f[12]:
                target.speed = float(f[12])
            if f[13]:
                target.heading = float(f[13])
            if f[14] and f[15]:
                target.lat = float(f[14])
                target.lon = float(f[15])
        except ValueError:
            pass
        squawk = f[17].strip()
        if squawk:
            target.squawk = squawk

        if self.cfg.db:
            info = self.cfg.db.lookup(icao)
            if info:
                target.registration = info.registration
                target.aircraft_type = info.type
                target.typecode = info.typecode
                target.owner = info.owner or info.operator
                target.category = classify(icao, info.typecode, info.operator, info.owner, info.type)

        asyncio.create_task(self.tracker.upsert(target))
