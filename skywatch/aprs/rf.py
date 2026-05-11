"""APRS RF decoder: rtl_fm | multimon-ng pipeline.

Spawns rtl_fm tuned to the configured APRS frequency (default 144.390 MHz US)
and pipes 22050 Hz mono S16LE FM audio into multimon-ng's AFSK1200 demodulator.
multimon-ng emits decoded packets as TNC2 lines prefixed with "APRS:"; we feed
those to the same parser/store the APRS-IS client uses, tagged source="RF".
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .parser import parse_aprs_packet
from .store import APRSStore, APRSStation, APRSMessage

log = logging.getLogger("skywatch.aprs.rf")

_AUDIO_RATE = 22050  # multimon-ng AFSK1200 expects 22050 Hz mono S16LE
_DEFAULT_FREQ = "144.390M"  # North-American APRS calling frequency

# Repo-bundled Windows binaries land here (rtl_fm.exe ships with the AIS-catcher
# bundle; multimon-ng.exe must be dropped in by the user).
_BUNDLED_TOOLS = Path(__file__).resolve().parents[2] / "tools" / "win64"


def _find_binary(configured: str, *aliases: str) -> Optional[str]:
    """Look up a binary on PATH, then in tools/win64/ as fallback."""
    for name in (configured, *aliases):
        if not name:
            continue
        found = shutil.which(name)
        if found:
            return found
    for name in (configured, *aliases):
        if not name:
            continue
        candidate = _BUNDLED_TOOLS / name
        if candidate.is_file():
            return str(candidate)
        if not name.lower().endswith(".exe"):
            candidate = _BUNDLED_TOOLS / f"{name}.exe"
            if candidate.is_file():
                return str(candidate)
    return None


@dataclass
class APRSRFConfig:
    rtl_fm_path: str = "rtl_fm"
    multimon_path: str = "multimon-ng"
    device_index: int = 0
    freq: str = _DEFAULT_FREQ
    gain: float = 0.0  # 0 = auto


class APRSRF:
    def __init__(self, cfg: APRSRFConfig, store: APRSStore) -> None:
        self.cfg = cfg
        self.store = store
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._rtl_fm: Optional[subprocess.Popen] = None
        self._decoder: Optional[subprocess.Popen] = None
        self._packets = 0
        self._decoded = 0
        self._rejected = 0

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="aprs-rf-run")

    async def stop(self) -> None:
        self._stop.set()
        for proc in (self._decoder, self._rtl_fm):
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        for proc in (self._decoder, self._rtl_fm):
            if proc:
                try:
                    await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=3.0)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except OSError:
                        pass
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, ConnectionError, OSError):
                pass

    async def _run(self) -> None:
        rtl_fm = _find_binary(self.cfg.rtl_fm_path, "rtl_fm", "rtl_fm.exe")
        if not rtl_fm:
            log.error("rtl_fm not found on PATH or in tools/win64/. Install "
                      "RTL-SDR tools (e.g. drop rtl_fm.exe into tools/win64/).")
            return
        multimon = _find_binary(self.cfg.multimon_path, "multimon-ng", "multimon-ng.exe")
        if not multimon:
            log.error(
                "multimon-ng not found on PATH or in tools/win64/. Download the "
                "Windows pre-built binary from "
                "https://github.com/EliasOenal/multimon-ng/releases and drop "
                "multimon-ng.exe into tools/win64/, then click Start again."
            )
            return

        rtl_args = [
            rtl_fm, "-f", self.cfg.freq, "-M", "fm",
            "-s", str(_AUDIO_RATE), "-d", str(self.cfg.device_index),
            "-l", "0", "-E", "deemp", "-",
        ]
        if self.cfg.gain and self.cfg.gain > 0:
            rtl_args.extend(["-g", str(int(self.cfg.gain))])
        mm_args = [multimon, "-t", "raw", "-a", "AFSK1200", "-A", "-"]

        log.info("starting APRS RF: %s | %s", " ".join(rtl_args), " ".join(mm_args))
        try:
            self._rtl_fm = subprocess.Popen(
                rtl_args,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._decoder = subprocess.Popen(
                mm_args,
                stdin=self._rtl_fm.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            # Close our copy of rtl_fm's stdout so SIGPIPE flows correctly
            # if multimon-ng exits first.
            assert self._rtl_fm.stdout is not None
            self._rtl_fm.stdout.close()
        except Exception as e:
            log.error("APRS RF spawn failed: %s", e)
            return

        # Bridge multimon-ng's stdout into the asyncio loop. Windows's Proactor
        # loop can't IOCP-register a regular subprocess pipe handle, so use a
        # blocking reader thread that pushes lines through an asyncio.Queue.
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=1024)
        decoder_stdout = self._decoder.stdout
        assert decoder_stdout is not None

        def _reader_thread() -> None:
            try:
                for line in iter(decoder_stdout.readline, b""):
                    loop.call_soon_threadsafe(queue.put_nowait, line)
            except Exception as e:
                log.exception(f"Failed to read APRS thread: {e}")

            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        import threading
        threading.Thread(target=_reader_thread, name="aprs-rf-stdout", daemon=True).start()

        log.info("APRS RF tuned to %s on device #%d", self.cfg.freq, self.cfg.device_index)
        try:
            while not self._stop.is_set():
                line = await queue.get()
                if line is None:
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if not text or not text.startswith("APRS:"):
                    continue
                self._packets += 1
                tnc2 = text[len("APRS:"):].strip()
                await self._handle_packet(tnc2)
        finally:
            log.info("APRS RF: %d packets, %d decoded, %d rejected",
                     self._packets, self._decoded, self._rejected)

    async def _handle_packet(self, raw: str) -> None:
        p = parse_aprs_packet(raw)
        if not p:
            self._rejected += 1
            return
        self._decoded += 1
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
            last_packet=raw, source="RF",
        )
        await self.store.upsert(st)
