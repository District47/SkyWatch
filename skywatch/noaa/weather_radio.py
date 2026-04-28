"""NOAA Weather Radio (NWR) receiver via rtl_fm. Mirrors internal/noaa/weather_radio.go.

- Spawns rtl_fm tuned to the chosen NWR channel (162.4 - 162.55 MHz).
- Streams 16-bit signed PCM mono @ 48 kHz to subscribers (WAV-wrapped).
- Periodic RMS computation for signal-level UI feedback.
- /scan endpoint cycles channels briefly to find which are active.
"""
from __future__ import annotations

import asyncio
import logging
import math
import shutil
import struct
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

log = logging.getLogger("skywatch.noaa.nwr")

NWR_FREQUENCIES = [
    {"freq_mhz": 162.400, "name": "WX1"},
    {"freq_mhz": 162.425, "name": "WX2"},
    {"freq_mhz": 162.450, "name": "WX3"},
    {"freq_mhz": 162.475, "name": "WX4"},
    {"freq_mhz": 162.500, "name": "WX5"},
    {"freq_mhz": 162.525, "name": "WX6"},
    {"freq_mhz": 162.550, "name": "WX7"},
]

_SAMPLE_RATE = 48000
_BYTES_PER_SAMPLE = 2  # int16 mono
_GAIN_DB_DEFAULT = "49.6"
_SCAN_TIMEOUT = 4.0
_SCAN_SAMPLE_RATE = 22050
_SIGNAL_THRESHOLD_DB = -30.0


@dataclass
class NWRChannelScan:
    name: str
    frequency_mhz: float
    signal_db: float
    active: bool


@dataclass
class NWRStatus:
    running: bool = False
    frequency_mhz: float = 0.0
    name: str = ""
    device: int = 0
    signal_db: float = -120.0


def wav_header_streaming() -> bytes:
    """Build a streaming WAV header (data chunk size set to 0xFFFFFFFF)."""
    sr = _SAMPLE_RATE
    byte_rate = sr * _BYTES_PER_SAMPLE
    return (
        b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, byte_rate, _BYTES_PER_SAMPLE, 16)
        + b"data" + struct.pack("<I", 0xFFFFFFFF)
    )


class NWRReceiver:
    def __init__(self, rtl_fm_path: str = "rtl_fm") -> None:
        self.rtl_fm_path = rtl_fm_path
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._buffer: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._status = NWRStatus()
        self._signal_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._subscribers: list[asyncio.Queue[bytes]] = []

    @property
    def status(self) -> NWRStatus:
        return self._status

    async def start(self, frequency_mhz: float, device: int = 0) -> None:
        await self.stop()
        binary = shutil.which(self.rtl_fm_path) or self.rtl_fm_path
        args = [
            binary,
            "-f", f"{int(frequency_mhz * 1_000_000)}",
            "-M", "fm",
            "-s", str(_SAMPLE_RATE),
            "-g", _GAIN_DB_DEFAULT,
            "-d", str(device),
            "-E", "deemp",
        ]
        log.info("starting NWR rtl_fm: %s", " ".join(args))
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Stream stderr to the log in the background so the user sees
        # rtl_fm's complaint (e.g. "usb_open error", "No supported devices
        # found") instead of silent failure. Also lets us detect early death.
        async def _drain_stderr(proc):
            assert proc.stderr is not None
            while True:
                line = await proc.stderr.readline()
                if not line:
                    return
                msg = line.decode(errors="replace").rstrip()
                if msg:
                    log.info("rtl_fm: %s", msg)
        self._stderr_task = asyncio.create_task(_drain_stderr(self._proc), name="nwr-stderr")

        # Catch the common case: rtl_fm exits immediately because the
        # device is busy (already in use by ADS-B/AIS) or the WinUSB
        # driver isn't bound. Wait briefly, then check.
        await asyncio.sleep(0.5)
        if self._proc.returncode is not None:
            log.error("rtl_fm exited immediately with code %s — device may be in use by another module, or WinUSB driver not bound (run Zadig).", self._proc.returncode)
            self._status = NWRStatus()
            return

        name = next((c["name"] for c in NWR_FREQUENCIES if abs(c["freq_mhz"] - frequency_mhz) < 0.001), "")
        self._status = NWRStatus(running=True, frequency_mhz=frequency_mhz, name=name, device=device)
        self._task = asyncio.create_task(self._pump(), name="nwr-pump")

    async def stop(self) -> None:
        self._status = NWRStatus()
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
                await asyncio.wait_for(self._task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        if self._stderr_task:
            try:
                await asyncio.wait_for(self._stderr_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
            self._stderr_task = None
        # Drain subscribers
        for q in list(self._subscribers):
            try:
                q.put_nowait(b"")
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()

    async def _pump(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        sample_count = 0
        sq_sum = 0.0
        try:
            while True:
                chunk = await self._proc.stdout.read(4096)
                if not chunk:
                    break
                # RMS for signal-level feedback (1-sec window).
                samples = struct.unpack(f"<{len(chunk)//2}h", chunk[: (len(chunk)//2) * 2])
                for s in samples:
                    sq_sum += (s / 32768.0) ** 2
                sample_count += len(samples)
                if sample_count >= _SAMPLE_RATE:
                    rms = math.sqrt(sq_sum / sample_count) + 1e-9
                    self._status.signal_db = 20.0 * math.log10(rms)
                    sample_count = 0
                    sq_sum = 0.0
                # Fan-out to subscribers (drop chunks if queues are full).
                for q in self._subscribers:
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        pass
        except Exception as e:
            log.warning("NWR pump error: %s", e)

    async def stream(self) -> AsyncIterator[bytes]:
        """Yield WAV-encapsulated bytes for an HTTP audio client."""
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._subscribers.append(q)
        try:
            yield wav_header_streaming()
            while True:
                chunk = await q.get()
                if not chunk:
                    return
                yield chunk
        finally:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    async def scan(self, device: int = 0) -> list[NWRChannelScan]:
        """Briefly tune each NWR frequency, measure RMS, return sorted results."""
        results: list[NWRChannelScan] = []
        for ch in NWR_FREQUENCIES:
            db = await self._measure_signal(ch["freq_mhz"], device)
            results.append(NWRChannelScan(
                name=ch["name"], frequency_mhz=ch["freq_mhz"],
                signal_db=db, active=db > _SIGNAL_THRESHOLD_DB,
            ))
        return results

    async def _measure_signal(self, frequency_mhz: float, device: int) -> float:
        binary = shutil.which(self.rtl_fm_path) or self.rtl_fm_path
        args = [
            binary,
            "-f", f"{int(frequency_mhz * 1_000_000)}",
            "-M", "fm",
            "-s", str(_SCAN_SAMPLE_RATE),
            "-g", _GAIN_DB_DEFAULT,
            "-d", str(device),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return -120.0
        try:
            data = await asyncio.wait_for(proc.stdout.read(_SCAN_SAMPLE_RATE * 2 * 1), timeout=_SCAN_TIMEOUT)
        except asyncio.TimeoutError:
            data = b""
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        if not data:
            return -120.0
        samples = struct.unpack(f"<{len(data)//2}h", data[: (len(data)//2) * 2])
        if not samples:
            return -120.0
        rms = math.sqrt(sum((s / 32768.0) ** 2 for s in samples) / len(samples)) + 1e-9
        return 20.0 * math.log10(rms)
