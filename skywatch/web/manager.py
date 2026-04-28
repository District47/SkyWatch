"""Module manager — owns lifecycle for ADS-B, AIS, NOAA tracker, APRS-IS, etc.

Mirrors the dispatch logic spread across cmd/skywatch/main.go and the start/stop
HTTP routes in internal/web/server.go.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..tracker import Tracker
from ..adsb import ADSB, ADSBConfig, OpenSky, OpenSkyConfig, NativeADSB, NativeADSBConfig, AircraftDB
from ..ais import AIS, AISConfig, AISStream, AISStreamConfig
from ..aprs import APRSStore, APRSISClient, APRSISConfig
from ..noaa import NOAATracker, NWRReceiver, APTCapture, APTConfig, CaptureResult
from ..remoteid import RemoteID, RemoteIDConfig, BLEScanner

log = logging.getLogger("skywatch.manager")


@dataclass
class ModuleStatus:
    name: str
    enabled: bool = False
    running: bool = False
    device: int = -1
    error: str = ""

    def to_json(self) -> dict:
        return self.__dict__


class Manager:
    def __init__(self, tracker: Tracker, aprs_store: APRSStore) -> None:
        self.tracker = tracker
        self.aprs_store = aprs_store
        self.aircraft_db = AircraftDB(Path("data/aircraft.json"))
        self.adsb: Optional[ADSB] = None
        self.adsb_native: Optional[NativeADSB] = None
        self.opensky: Optional[OpenSky] = None
        self.ais: Optional[AIS] = None
        self.aisstream: Optional[AISStream] = None
        self.aprs_is: Optional[APRSISClient] = None
        self.remoteid: Optional[RemoteID] = None
        self.remoteid_ble: Optional[BLEScanner] = None
        # Remember the WiFi interface passed via CLI so the dashboard's
        # Start/Stop button can restart drone-RID without needing to re-type it.
        self.remoteid_interface: str = ""
        self.remoteid_monitor: bool = True
        self.remoteid_channel: int = 6
        self.noaa_tracker = NOAATracker()
        self.nwr = NWRReceiver()
        self.apt = APTCapture(APTConfig())
        self._captures: list[CaptureResult] = []
        self._device_assignments: dict[int, str] = {}
        self._lock = asyncio.Lock()

    def assigned_devices(self) -> dict[int, str]:
        return dict(self._device_assignments)

    async def status(self) -> list[ModuleStatus]:
        adsb_running = bool(
            (self.adsb and self.adsb._task and not self.adsb._task.done())
            or (self.adsb_native and self.adsb_native.running)
        )
        opensky_running = bool(self.opensky and self.opensky._task and not self.opensky._task.done())
        ais_running = bool(self.ais and self.ais._task and not self.ais._task.done())
        aisstream_running = bool(self.aisstream and self.aisstream._task and not self.aisstream._task.done())

        # Frontend keys on 'adsb' / 'ais' — merge the online-feed state into them
        # so the Start/Stop button flips when either path is active. Device -2
        # signals "online feed" to the dashboard.
        out = [
            ModuleStatus(name="adsb",
                         enabled=(self.adsb is not None) or (self.adsb_native is not None) or (self.opensky is not None),
                         running=adsb_running or opensky_running,
                         device=(
                             self.adsb_native.cfg.device_index if (self.adsb_native and self.adsb_native.running)
                             else self.adsb.cfg.device_index if (self.adsb and self.adsb._task and not self.adsb._task.done())
                             else (-2 if opensky_running else -1)
                         )),
            ModuleStatus(name="ais",
                         enabled=self.ais is not None or self.aisstream is not None,
                         running=ais_running or aisstream_running,
                         device=(self.ais.cfg.device_index if ais_running else (-2 if aisstream_running else -1))),
            ModuleStatus(name="opensky",
                         enabled=self.opensky is not None,
                         running=opensky_running),
            ModuleStatus(name="aisstream",
                         enabled=self.aisstream is not None,
                         running=aisstream_running),
            ModuleStatus(name="aprs-is",
                         enabled=self.aprs_is is not None,
                         running=bool(self.aprs_is and self.aprs_is._task and not self.aprs_is._task.done())),
            ModuleStatus(name="remoteid",
                         enabled=self.remoteid is not None,
                         running=bool(self.remoteid and self.remoteid._task and not self.remoteid._task.done())),
            # Frontend uses 'drone' as the module name; alias here so the
            # Start/Stop button on the Drones tab can read its state.
            ModuleStatus(name="drone",
                         enabled=self.remoteid is not None,
                         running=bool(self.remoteid and self.remoteid._task and not self.remoteid._task.done())),
            ModuleStatus(name="nwr",
                         enabled=True,
                         running=self.nwr.status.running,
                         device=self.nwr.status.device),
        ]
        return out

    async def start_adsb(self, device: int, gain: float = 0.0, readsb_path: str = "readsb",
                        external_host: str = "") -> None:
        """Start ADS-B. Picks the native pure-Python decoder when a real device
        index is given (no readsb binary required). The legacy readsb-spawn
        path is still used when external_host is provided."""
        async with self._lock:
            if self.adsb:
                await self.adsb.stop()
                self.adsb = None
            if self.adsb_native:
                await self.adsb_native.stop()
                self.adsb_native = None

            if external_host:
                cfg = ADSBConfig(
                    readsb_path=readsb_path, device_index=device, gain=gain,
                    external_host=external_host, db=self.aircraft_db,
                )
                self.adsb = ADSB(cfg, self.tracker)
                await self.adsb.start()
            else:
                self.adsb_native = NativeADSB(NativeADSBConfig(
                    device_index=device, gain=gain, db=self.aircraft_db,
                ), self.tracker)
                await self.adsb_native.start()
                if device >= 0:
                    self._device_assignments[device] = "adsb"

    async def stop_adsb(self) -> None:
        async with self._lock:
            if self.adsb:
                dev = self.adsb.cfg.device_index
                await self.adsb.stop()
                self.adsb = None
                self._device_assignments.pop(dev, None)
            if self.adsb_native:
                dev = self.adsb_native.cfg.device_index
                await self.adsb_native.stop()
                self.adsb_native = None
                self._device_assignments.pop(dev, None)

    async def start_opensky(self, lat: float = 0.0, lon: float = 0.0, radius_km: float = 0.0) -> None:
        async with self._lock:
            cfg = OpenSkyConfig(enabled=True, db=self.aircraft_db)
            if lat or lon:
                cfg.center_lat, cfg.center_lon = lat, lon
            if radius_km:
                cfg.radius_km = radius_km
            if self.opensky:
                await self.opensky.stop()
            self.opensky = OpenSky(cfg, self.tracker)
            await self.opensky.start()

    async def stop_opensky(self) -> None:
        async with self._lock:
            if self.opensky:
                await self.opensky.stop()
                self.opensky = None

    async def start_ais(self, device: int, gain: float = 0.0, rtl_ais_path: str = "rtl_ais",
                       external_host: str = "") -> None:
        async with self._lock:
            if self.ais:
                await self.ais.stop()
            self.ais = AIS(AISConfig(
                rtl_ais_path=rtl_ais_path, device_index=device,
                gain=gain, external_host=external_host,
            ), self.tracker)
            await self.ais.start()
            if device >= 0 and not external_host:
                self._device_assignments[device] = "ais"

    async def stop_ais(self) -> None:
        async with self._lock:
            if self.ais:
                dev = self.ais.cfg.device_index
                await self.ais.stop()
                self.ais = None
                self._device_assignments.pop(dev, None)

    async def start_aisstream(self, api_key: str, lat: float = 0.0, lon: float = 0.0,
                             radius_km: float = 0.0) -> None:
        async with self._lock:
            cfg = AISStreamConfig(api_key=api_key)
            if lat or lon:
                cfg.center_lat, cfg.center_lon = lat, lon
            if radius_km:
                cfg.radius_km = radius_km
            if self.aisstream:
                await self.aisstream.stop()
            self.aisstream = AISStream(cfg, self.tracker)
            await self.aisstream.start()

    async def stop_aisstream(self) -> None:
        async with self._lock:
            if self.aisstream:
                await self.aisstream.stop()
                self.aisstream = None

    async def start_aprs_is(self, cfg: APRSISConfig) -> None:
        async with self._lock:
            if self.aprs_is:
                await self.aprs_is.stop()
            self.aprs_is = APRSISClient(cfg, self.aprs_store)
            await self.aprs_is.start()

    async def stop_aprs_is(self) -> None:
        async with self._lock:
            if self.aprs_is:
                await self.aprs_is.stop()
                self.aprs_is = None

    async def start_remoteid(self, interface: str, monitor: bool = True, channel: int = 6) -> None:
        async with self._lock:
            if self.remoteid:
                await self.remoteid.stop()
            self.remoteid = RemoteID(RemoteIDConfig(
                interface=interface, auto_monitor=monitor, channel=channel,
            ), self.tracker)
            self.remoteid_interface = interface
            self.remoteid_monitor = monitor
            self.remoteid_channel = channel
            await self.remoteid.start()
            # BLE Drone-RID runs on the host's Bluetooth radio — no UI needed.
            if self.remoteid_ble is None:
                self.remoteid_ble = BLEScanner(self.tracker)
            try:
                await self.remoteid_ble.start()
            except Exception as e:
                log.warning("BLE Drone-RID start failed: %s", e)

    async def stop_remoteid(self) -> None:
        async with self._lock:
            if self.remoteid:
                await self.remoteid.stop()
                self.remoteid = None
            if self.remoteid_ble:
                try:
                    await self.remoteid_ble.stop()
                except Exception:
                    pass
                self.remoteid_ble = None

    async def start_noaa_tracker(self, lat: float = 0.0, lon: float = 0.0) -> None:
        self.noaa_tracker.set_observer(lat, lon)
        await self.noaa_tracker.start()

    async def capture_apt(self, satellite: str, frequency_mhz: float, duration_seconds: int) -> CaptureResult:
        result = await self.apt.capture(satellite, frequency_mhz, duration_seconds)
        self._captures.append(result)
        return result

    def captures(self) -> list[CaptureResult]:
        return list(self._captures)

    async def shutdown(self) -> None:
        for stop in (
            self.stop_adsb, self.stop_opensky, self.stop_ais, self.stop_aisstream,
            self.stop_aprs_is, self.stop_remoteid,
        ):
            try:
                await stop()
            except Exception as e:
                log.warning("shutdown step %s: %s", stop, e)
        try:
            await self.noaa_tracker.stop()
        except Exception:
            pass
        try:
            await self.nwr.stop()
        except Exception:
            pass
