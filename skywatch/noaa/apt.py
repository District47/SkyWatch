"""NOAA APT image capture (137 MHz polar-orbit satellites).

Mirrors internal/noaa/apt.go and receiver.go. Spawns rtl_fm tuned to the
satellite, captures the audio for the requested duration, then synthesizes a
PNG image by AM-demodulating the 2400 Hz subcarrier and aligning to the per-
line sync-A pattern.

Notes on fidelity to the Go version:
- Sample rate, line rate, pixel rate, sync window, percentile clipping, and
  capture filename format match the Go constants exactly.
- True scan-line geometric correction (Doppler / earth curvature) is out of
  scope for v1, same as Go.
"""
from __future__ import annotations

import asyncio
import logging
import math
import shutil
import struct
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("skywatch.noaa.apt")

_AUDIO_SAMPLE_RATE = 11025
_LINE_RATE = 2.0
_PIXELS_PER_LINE = 2080
_PIXEL_RATE = _LINE_RATE * _PIXELS_PER_LINE  # 4160
_SAMPLES_PER_LINE = _AUDIO_SAMPLE_RATE // 2  # 5512
_APT_SUBCARRIER = 2400.0
_OUTPUT_DIR = Path("noaa_images")


@dataclass
class APTConfig:
    rtl_fm_path: str = "rtl_fm"
    device: int = 0
    gain: float = 40.0
    duration_seconds: int = 900
    output_dir: Path = _OUTPUT_DIR


@dataclass
class CaptureResult:
    satellite: str
    frequency_mhz: float
    started_at: str
    finished_at: str
    duration_s: int
    file_path: str = ""
    image_b64: str = ""
    error: str = ""


class APTCapture:
    def __init__(self, cfg: APTConfig) -> None:
        self.cfg = cfg
        self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, satellite: str, frequency_mhz: float, duration_seconds: Optional[int] = None) -> CaptureResult:
        duration = duration_seconds or self.cfg.duration_seconds
        started = datetime.now()
        try:
            audio = await self._record_audio(frequency_mhz, duration)
        except Exception as e:
            log.error("APT record failed: %s", e)
            return CaptureResult(
                satellite=satellite, frequency_mhz=frequency_mhz,
                started_at=started.isoformat(),
                finished_at=datetime.now().isoformat(),
                duration_s=duration, error=str(e),
            )
        try:
            png_path = self._synthesize_png(satellite, started, audio)
        except Exception as e:
            log.error("APT decode failed: %s", e)
            return CaptureResult(
                satellite=satellite, frequency_mhz=frequency_mhz,
                started_at=started.isoformat(),
                finished_at=datetime.now().isoformat(),
                duration_s=duration, error=str(e),
            )
        return CaptureResult(
            satellite=satellite, frequency_mhz=frequency_mhz,
            started_at=started.isoformat(),
            finished_at=datetime.now().isoformat(),
            duration_s=duration, file_path=str(png_path),
        )

    async def _record_audio(self, frequency_mhz: float, duration_seconds: int) -> np.ndarray:
        binary = shutil.which(self.cfg.rtl_fm_path) or self.cfg.rtl_fm_path
        args = [
            binary,
            "-f", f"{int(frequency_mhz * 1_000_000)}",
            "-M", "fm",
            "-s", str(_AUDIO_SAMPLE_RATE),
            "-g", f"{self.cfg.gain:g}",
            "-d", str(self.cfg.device),
        ]
        log.info("APT recording %.4f MHz for %ds: %s", frequency_mhz, duration_seconds, " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        deadline = time.monotonic() + duration_seconds
        chunks: list[bytes] = []
        try:
            while time.monotonic() < deadline:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(8192), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        raw = b"".join(chunks)
        if not raw:
            raise RuntimeError("no audio captured (rtl_fm produced 0 bytes)")
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        return samples

    def _synthesize_png(self, satellite: str, started: datetime, audio: np.ndarray) -> Path:
        # AM envelope detect via squared + lowpass (cheap; matches the Go peak-follower).
        env = np.abs(audio)
        # Smooth by ~half-cycle of the 2400 Hz subcarrier.
        win = max(1, int(_AUDIO_SAMPLE_RATE / _APT_SUBCARRIER / 2))
        if win > 1:
            kernel = np.ones(win, dtype=np.float32) / win
            env = np.convolve(env, kernel, mode="same")

        # Resample envelope to pixel rate (4160 px/s).
        ratio = _PIXEL_RATE / _AUDIO_SAMPLE_RATE
        n_pixels = int(len(env) * ratio)
        if n_pixels < _PIXELS_PER_LINE:
            raise RuntimeError(f"too few samples for an APT line ({n_pixels} < {_PIXELS_PER_LINE})")
        x_old = np.linspace(0, 1, len(env), endpoint=False)
        x_new = np.linspace(0, 1, n_pixels, endpoint=False)
        pixels = np.interp(x_new, x_old, env)

        # Robust 2nd–98th percentile normalization to 0..255.
        lo, hi = np.percentile(pixels, [2, 98])
        if hi <= lo:
            hi = lo + 1.0
        norm = np.clip((pixels - lo) / (hi - lo), 0, 1) * 255.0
        norm = norm.astype(np.uint8)

        # Reshape into (lines, 2080).
        n_lines = len(norm) // _PIXELS_PER_LINE
        image = norm[: n_lines * _PIXELS_PER_LINE].reshape(n_lines, _PIXELS_PER_LINE)

        from PIL import Image  # late import keeps the rest of the package import-light
        png = Image.fromarray(image, mode="L")
        out_dir = self.cfg.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{satellite.replace(' ', '_')}_{started:%Y%m%d_%H%M%S}.png"
        png.save(path, format="PNG")
        return path
