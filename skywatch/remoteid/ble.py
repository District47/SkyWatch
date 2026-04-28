"""BLE 4/5 Drone Remote ID scanner.

Listens for ASTM F3411 advertisements via the host's Bluetooth radio.
Open Drone ID messages can ride in BLE Service Data with UUID 0xFFFA
(the ASTM-assigned SIG UUID) — the inner payload uses the same message
structure we parse for WiFi, so we reuse parse_remote_id_ie + the
internal state-accumulation helpers.

Many DJI drones (Mini 3, Mini 4 Pro, Mavic 3) broadcast RID on BLE,
so this is required to catch them when the WiFi path comes up empty.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ..tracker import Target, Tracker, TYPE_DRONE
from .remoteid import parse_remote_id_ie, _apply_message, _DroneState

log = logging.getLogger("skywatch.remoteid.ble")

# Bluetooth-SIG-assigned UUID for ASTM F3411 Open Drone ID.
_ASTM_UUID_FULL = "0000fffa-0000-1000-8000-00805f9b34fb"
_ASTM_UUID_SHORT = "fffa"


class BLEScanner:
    def __init__(self, tracker: Tracker) -> None:
        self.tracker = tracker
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._scanner = None
        self._states: dict[str, _DroneState] = {}
        # Visible counters so the dashboard can show "BLE adv frames seen".
        self.frames_total = 0
        self.frames_rid = 0
        self.last_frame_at = 0.0
        self.last_rid_at = 0.0

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="remoteid-ble")

    async def stop(self) -> None:
        self._stop.set()
        if self._scanner:
            try:
                await self._scanner.stop()
            except Exception:
                pass
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def _run(self) -> None:
        try:
            from bleak import BleakScanner  # type: ignore
        except Exception as e:
            log.error("bleak unavailable; BLE Drone-RID disabled: %s", e)
            return

        loop = asyncio.get_event_loop()
        last_log = time.monotonic()

        def callback(device, ad_data):
            nonlocal last_log
            self.frames_total += 1
            self.last_frame_at = time.time()
            sd = getattr(ad_data, "service_data", None) or {}
            for uuid, payload in sd.items():
                u = str(uuid).lower()
                if _ASTM_UUID_FULL in u or u.endswith(_ASTM_UUID_SHORT):
                    try:
                        self._handle_payload(device.address, bytes(payload), loop)
                    except Exception as e:
                        log.debug("BLE RID parse error: %s", e)
            now = time.monotonic()
            if (now - last_log) >= 15.0:
                log.info("remoteid BLE: %d adv frames (%d Drone-RID)",
                         self.frames_total, self.frames_rid)
                last_log = now

        try:
            # Active scan returns scan-response data too, which often carries
            # the bigger ASTM payload. Active is fine for receive-only ID work.
            self._scanner = BleakScanner(detection_callback=callback, scanning_mode="active")
            await self._scanner.start()
            log.info("BLE Drone-RID scanner started")
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
        except Exception as e:
            log.error("BLE scanner failed: %s", e)
        finally:
            try:
                if self._scanner:
                    await self._scanner.stop()
            except Exception:
                pass
            self._scanner = None

    def _handle_payload(self, addr: str, payload: bytes, loop: asyncio.AbstractEventLoop) -> None:
        # ASTM F3411 BLE prepends a 1-byte advertisement counter; the rest
        # is the same Open Drone ID message body we already parse for WiFi.
        if len(payload) < 2:
            return
        body = payload[1:]
        self.frames_rid += 1
        self.last_rid_at = time.time()
        state = self._states.setdefault(addr, _DroneState())
        for msg_type, sub in parse_remote_id_ie(body):
            ready = _apply_message(state, msg_type, sub)
            if ready:
                target = Target(
                    id=f"DRONE-{state.uas_id}",
                    type=TYPE_DRONE,
                    callsign=state.uas_id,
                    drone_id=state.uas_id,
                    operator=state.operator_id,
                    lat=state.lat, lon=state.lon,
                    altitude=state.altitude_m,
                    speed=state.speed_kt,
                    heading=state.heading,
                )
                asyncio.run_coroutine_threadsafe(self.tracker.upsert(target), loop)
