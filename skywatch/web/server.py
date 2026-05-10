"""FastAPI dashboard + REST API + WebSocket. Mirrors internal/web/server.go.

Every route from the Go server is reproduced here with matching JSON shapes,
so the existing static/index.html + js/app.js continue to work unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..tracker import Tracker, Target
from ..sdr import list_devices
from ..adsb import AircraftDB
from ..ais import AISStream, lookup_vessel_photo
from ..remoteid import list_wifi_interfaces
from ..aprs import APRSStore, APRSISConfig, compute_passcode, build_position_beacon, build_message
from ..aprs.tx import build_status
from ..noaa import NOAA_SATELLITES, NWR_TRANSMITTERS
from ..noaa.weather_api import fetch_alerts, fetch_forecast
from ..util.geo import DEFAULT_LAT, DEFAULT_LON, DEFAULT_RADIUS_KM
from .manager import Manager, ModuleStatus, DeviceBusy
from . import zadig
from . import npcap
from . import vcredist
from .. import health as health_mod

log = logging.getLogger("skywatch.web")

_BROADCAST_MIN_INTERVAL = 0.5  # seconds; matches Go


_API_KEYS_FILE = Path("data/api_keys.json")


def _load_api_keys() -> dict:
    if not _API_KEYS_FILE.exists():
        return {}
    try:
        return json.loads(_API_KEYS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.exception(f"Failed to load json: {e}")
        return {}


def _save_api_keys(keys: dict) -> None:
    _API_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _API_KEYS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(keys), encoding="utf-8")
    tmp.replace(_API_KEYS_FILE)
    try:
        import os
        os.chmod(_API_KEYS_FILE, 0o600)
    except Exception as e:
        log.exception(f"Failed to save api keys: {e}")


class WebSocketHub:
    """Maintains a list of connected WS clients and rate-limits broadcasts."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []
        self._lock = asyncio.Lock()
        self._dirty = asyncio.Event()
        self._last_broadcast = 0.0

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.append(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self._clients:
                self._clients.remove(ws)

    def mark_dirty(self) -> None:
        self._dirty.set()

    async def run_broadcaster(self, snapshot_fn) -> None:
        # Force-flush every N seconds even without a dirty event, so a
        # silently-dropped notification can never starve the dashboard of
        # updates. Each iteration is wrapped so a single bad cycle doesn't
        # kill the task.
        force_interval = 3.0
        while True:
            try:
                try:
                    await asyncio.wait_for(self._dirty.wait(), timeout=force_interval)
                except asyncio.TimeoutError:
                    pass  # periodic forced refresh
                self._dirty.clear()
                elapsed = time.monotonic() - self._last_broadcast
                if elapsed < _BROADCAST_MIN_INTERVAL:
                    await asyncio.sleep(_BROADCAST_MIN_INTERVAL - elapsed)
                payload = await snapshot_fn()
                self._last_broadcast = time.monotonic()
                async with self._lock:
                    clients = list(self._clients)
                if not clients:
                    continue
                data = json.dumps(payload, default=lambda o: getattr(o, "to_json", lambda: o.__dict__)())
                for ws in clients:
                    try:
                        await ws.send_text(data)
                    except Exception as e:
                        log.exception(f"Failed to send websocket text {e} {data}")
                        await self.remove(ws)
            except Exception as e:
                log.warning("ws broadcaster cycle error: %s", e)
                await asyncio.sleep(1.0)


def build_app(*, tracker: Tracker, aprs_store: APRSStore, manager: Manager,
              alerts=None, static_dir: Path, args=None, extra_startup=None) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # Startup
        asyncio.create_task(hub.run_broadcaster(snapshot), name="ws-broadcaster")
        async def _pruner():
            while True:
                await asyncio.sleep(10.0)
                try:
                    await tracker.prune(300)
                    await aprs_store.prune()
                    hub.mark_dirty()
                except Exception as e:
                    log.exception(f"Failed to prune aprs tracking: {e}")
        asyncio.create_task(_pruner(), name="pruner")
        if extra_startup is not None:
            try:
                await extra_startup()
            except Exception as e:
                log.warning("extra_startup failed: %s", e)
        yield
        # Shutdown
        try:
            await manager.shutdown()
        except Exception as e:
            log.warning("manager shutdown error: %s", e)

    app = FastAPI(title="SkyWatch", version="1.0.0", lifespan=_lifespan)
    hub = WebSocketHub()
    api_keys: dict = _load_api_keys()

    tracker.set_change_callback(hub.mark_dirty)

    async def snapshot() -> dict:
        targets = await tracker.snapshot()
        stations = await aprs_store.stations()
        messages = await aprs_store.messages()
        snap = {
            "targets": [t.to_json() for t in targets],
            "aprs": [s.to_json() for s in stations],
            "messages": [m.to_json() for m in messages],
        }
        if alerts is not None:
            snap["alert_zones"] = [z.to_json() for z in await alerts.list_zones()]
            snap["alert_events"] = [e.to_json() for e in await alerts.events()]
        return snap

    if alerts is not None:
        # When an alert fires, mark the WS dirty so the new event ships out
        # to clients on the next broadcast tick.
        alerts.set_event_callback(lambda _ev: hub.mark_dirty())

    # ---- Targets / status ----

    @app.get("/api/targets")
    async def api_targets():
        return await snapshot()

    @app.get("/api/health")
    async def api_health():
        # Some checks (DLL loads, shutil.which on a slow filesystem) are
        # synchronous; run off the event loop so the WS broadcaster doesn't
        # stall behind a dragging probe.
        checks = await asyncio.to_thread(health_mod.run_all)
        return {
            "summary": health_mod.summarize(checks),
            "checks": [c.to_json() for c in checks],
        }

    @app.get("/api/zadig/status")
    async def api_zadig_status():
        return zadig.status()

    @app.post("/api/zadig/launch")
    async def api_zadig_launch():
        # Off-thread because urlopen + ShellExecuteW are blocking; we don't
        # want to stall the WS broadcaster on a slow GitHub response.
        return await asyncio.to_thread(zadig.launch)

    @app.get("/api/npcap/status")
    async def api_npcap_status():
        return npcap.status()

    @app.post("/api/npcap/launch")
    async def api_npcap_launch():
        return await asyncio.to_thread(npcap.launch)

    @app.get("/api/vcredist/status")
    async def api_vcredist_status():
        return vcredist.status()

    @app.post("/api/vcredist/launch")
    async def api_vcredist_launch():
        return await asyncio.to_thread(vcredist.launch)

    @app.get("/api/devices")
    async def api_devices():
        devs = list_devices()
        assigned = manager.assigned_devices()
        out = []
        for d in devs:
            d.in_use = d.index in assigned
            d.assigned_to = assigned.get(d.index, "")
            out.append(d.to_json())
        return out

    @app.get("/api/status")
    async def api_status():
        st = await manager.status()
        return [s.to_json() for s in st]

    @app.post("/api/start")
    async def api_start(req: Request):
        try:
            return await _api_start_inner(req)
        except DeviceBusy as e:
            return JSONResponse({"error": str(e)}, status_code=409)

    async def _api_start_inner(req: Request):
        body = await req.json()
        module = body.get("module")
        # `device` may be omitted, null, -1 (none), or -2 (online feed). Coerce safely.
        raw_device = body.get("device")
        device = int(raw_device) if raw_device is not None else -1
        raw_gain = body.get("gain")
        gain = float(raw_gain) if raw_gain is not None else 0.0
        host = body.get("host") or ""

        # Optional bounds from the dashboard — used for online feeds so the
        # first poll already targets the visible map view.
        has_box = all(k in body for k in ("lamin", "lamax", "lomin", "lomax"))
        if has_box:
            box = (float(body["lamin"]), float(body["lamax"]),
                   float(body["lomin"]), float(body["lomax"]))
        else:
            box = None

        if module == "adsb":
            if device == -2:
                await manager.start_opensky()
                if box and manager.opensky:
                    manager.opensky.set_box(*box)
            else:
                # Use the visible-area centre as the CPR reference so a single
                # position message decodes immediately (no waiting for an
                # odd/even pair).
                ref_lat = (box[0] + box[1]) / 2 if box else 0.0
                ref_lon = (box[2] + box[3]) / 2 if box else 0.0
                await manager.start_adsb(device=device, gain=gain,
                                         external_host=host,
                                         reference_lat=ref_lat,
                                         reference_lon=ref_lon)
        elif module == "ais":
            if device == -2:
                key = api_keys.get("aisstream", "")
                if not key:
                    return JSONResponse({"error": "aisstream API key not configured (set it in the dashboard)"}, status_code=400)
                await manager.start_aisstream(api_key=key)
                if box and manager.aisstream:
                    await manager.aisstream.set_box(*box)
            else:
                await manager.start_ais(device=device, gain=gain, external_host=host)
        elif module == "opensky":
            await manager.start_opensky()
        elif module == "aisstream":
            key = api_keys.get("aisstream", "")
            if not key:
                return JSONResponse({"error": "aisstream API key not configured"}, status_code=400)
            await manager.start_aisstream(api_key=key)
        elif module in ("remoteid", "drone", "drone-wifi"):
            # 'drone-wifi' starts only the 802.11 sniffer; 'drone' / 'remoteid'
            # also auto-start BLE for back-compat with the CLI -wifi flag and
            # the legacy single-button UI.
            iface = body.get("interface") or manager.remoteid_interface
            if not iface:
                return JSONResponse(
                    {"error": "no WiFi interface configured (start the server with -wifi <iface>)"},
                    status_code=400,
                )
            monitor = bool(body.get("monitor", manager.remoteid_monitor))
            channel = int(body.get("channel", manager.remoteid_channel))
            if module == "drone-wifi":
                await manager.start_remoteid_wifi(iface, monitor, channel)
            else:
                await manager.start_remoteid(iface, monitor, channel)
        elif module == "drone-ble":
            # No interface needed — uses the host Bluetooth radio (or whichever
            # USB BT dongle the OS has configured as default).
            await manager.start_remoteid_ble()
        elif module == "noaa":
            # Frontend uses this for the NOAA auto-capture daemon. The tracker
            # is already running; just acknowledge so the UI updates.
            return {"ok": True, "note": "NOAA tracker is always running; use /api/noaa/capture for one-shot captures"}
        elif module == "aprs-is":
            await manager.start_aprs_is(aprs_runtime_cfg)
        elif module == "aprs-sdr":
            if device < 0:
                return JSONResponse({"error": "select an RTL-SDR device for APRS RF"}, status_code=400)
            await manager.start_aprs_rf(device=device, gain=gain)
        elif module == "aprs-uvpro":
            return JSONResponse(
                {"error": "aprs-uvpro decoder not implemented yet"},
                status_code=501,
            )
        else:
            return JSONResponse({"error": f"unknown module {module!r}"}, status_code=400)
        return {"ok": True}

    @app.post("/api/stop")
    async def api_stop(req: Request):
        body = await req.json()
        module = body.get("module")
        if module == "adsb":
            await manager.stop_adsb()
            await manager.stop_opensky()
        elif module == "ais":
            await manager.stop_ais()
            await manager.stop_aisstream()
        elif module == "opensky":
            await manager.stop_opensky()
        elif module == "aisstream":
            await manager.stop_aisstream()
        elif module in ("remoteid", "drone"):
            await manager.stop_remoteid()
        elif module == "drone-wifi":
            await manager.stop_remoteid_wifi()
        elif module == "drone-ble":
            await manager.stop_remoteid_ble()
        elif module == "noaa":
            return {"ok": True}
        elif module == "aprs-is":
            await manager.stop_aprs_is()
        elif module == "aprs-sdr":
            await manager.stop_aprs_rf()
        elif module == "aprs-uvpro":
            return {"ok": True}
        else:
            return JSONResponse({"error": f"unknown module {module!r}"}, status_code=400)
        return {"ok": True}

    # ---- Aircraft DB ----

    @app.get("/api/aircraft/status")
    async def api_aircraft_status():
        return {"count": manager.aircraft_db.count()}

    @app.post("/api/aircraft/import")
    async def api_aircraft_import():
        added = await manager.aircraft_db.import_from_opensky()
        return {"imported": added, "count": manager.aircraft_db.count()}

    @app.post("/api/aircraft/bounds")
    async def api_aircraft_bounds(req: Request):
        body = await req.json()
        # Frontend sends Leaflet bounds (lamin/lomin/lamax/lomax). Old
        # lat/lon/radius_km form is still accepted for direct API callers.
        if "lamin" in body and "lamax" in body:
            min_lat = float(body["lamin"]); max_lat = float(body["lamax"])
            min_lon = float(body["lomin"]); max_lon = float(body["lomax"])
            if manager.opensky:
                manager.opensky.set_box(min_lat, max_lat, min_lon, max_lon)
            # Keep the native-decoder CPR reference at the box centre.
            if manager.adsb_native:
                manager.adsb_native.set_reference((min_lat + max_lat) / 2,
                                                  (min_lon + max_lon) / 2)
            return {"ok": True, "min_lat": min_lat, "max_lat": max_lat,
                    "min_lon": min_lon, "max_lon": max_lon}
        lat = float(body.get("lat", DEFAULT_LAT))
        lon = float(body.get("lon", DEFAULT_LON))
        radius = float(body.get("radius_km", DEFAULT_RADIUS_KM))
        if manager.opensky:
            manager.opensky.set_bounds(lat, lon, radius)
        if manager.adsb_native:
            manager.adsb_native.set_reference(lat, lon)
        return {"ok": True, "lat": lat, "lon": lon, "radius_km": radius}

    # ---- AIS ----

    @app.get("/api/vessel/photo")
    async def api_vessel_photo(name: str = ""):
        result = await lookup_vessel_photo(name)
        return result.to_json()

    @app.post("/api/ais/bounds")
    async def api_ais_bounds(req: Request):
        body = await req.json()
        if "lamin" in body and "lamax" in body:
            min_lat = float(body["lamin"]); max_lat = float(body["lamax"])
            min_lon = float(body["lomin"]); max_lon = float(body["lomax"])
            if manager.aisstream:
                await manager.aisstream.set_box(min_lat, max_lat, min_lon, max_lon)
            return {"ok": True, "min_lat": min_lat, "max_lat": max_lat,
                    "min_lon": min_lon, "max_lon": max_lon}
        lat = float(body.get("lat", DEFAULT_LAT))
        lon = float(body.get("lon", DEFAULT_LON))
        radius = float(body.get("radius_km", DEFAULT_RADIUS_KM))
        if manager.aisstream:
            await manager.aisstream.set_bounds(lat, lon, radius)
        return {"ok": True, "lat": lat, "lon": lon, "radius_km": radius}

    # ---- Drone Remote ID ----

    @app.get("/api/remoteid/interfaces")
    async def api_remoteid_interfaces():
        return {
            "interfaces": list_wifi_interfaces(),
            "current": manager.remoteid_interface or "",
        }

    @app.get("/api/remoteid/stats")
    async def api_remoteid_stats():
        r = manager.remoteid
        ble = manager.remoteid_ble
        wifi_running = bool(r and r._task and not r._task.done())
        ble_running = bool(ble and ble._task and not ble._task.done())
        return {
            # `running` = either band live, so the legacy "Sniffer not running."
            # banner clears the moment any band starts.
            "running": wifi_running or ble_running,
            "wifi_running": wifi_running,
            "interface": r.cfg.interface if r else "",
            "frames_total": r.frames_total if r else 0,
            "frames_mgmt": r.frames_mgmt if r else 0,
            "frames_rid": r.frames_rid if r else 0,
            "last_frame_at": r.last_frame_at if r else 0,
            "last_rid_at": r.last_rid_at if r else 0,
            "ble_running": ble_running,
            "ble_frames_total": ble.frames_total if ble else 0,
            "ble_frames_rid": ble.frames_rid if ble else 0,
            "ble_last_frame_at": ble.last_frame_at if ble else 0,
            "ble_last_rid_at": ble.last_rid_at if ble else 0,
        }

    # ---- Alert zones ----

    @app.get("/api/alerts/zones")
    async def api_alert_zones():
        if alerts is None:
            return []
        return [z.to_json() for z in await alerts.list_zones()]

    @app.post("/api/alerts/zones")
    async def api_alert_zones_create(req: Request):
        if alerts is None:
            raise HTTPException(503, "alerts not configured")
        body = await req.json()
        # Accept the new category_filters (list) plus the legacy
        # category_filter (single string) so old clients still work.
        cf_list = body.get("category_filters") or []
        if not cf_list and body.get("category_filter"):
            cf_list = [body["category_filter"]]
        zone = await alerts.add_zone(
            name=body.get("name", ""),
            lat=float(body.get("lat", 0.0)),
            lon=float(body.get("lon", 0.0)),
            radius_km=float(body.get("radius_km", 5.0)),
            target_types=body.get("target_types") or ["aircraft"],
            category_filters=cf_list,
            callsign_filter=body.get("callsign_filter", ""),
        )
        return zone.to_json()

    @app.delete("/api/alerts/zones/{zone_id}")
    async def api_alert_zones_delete(zone_id: str):
        if alerts is None:
            raise HTTPException(503, "alerts not configured")
        ok = await alerts.remove_zone(zone_id)
        if not ok:
            raise HTTPException(404, "zone not found")
        return {"ok": True}

    @app.get("/api/alerts/events")
    async def api_alert_events():
        if alerts is None:
            return []
        return [e.to_json() for e in await alerts.events()]

    # ---- APRS ----

    aprs_runtime_cfg = APRSISConfig()

    @app.get("/api/aprs/config")
    async def api_aprs_get_config():
        return aprs_runtime_cfg.__dict__

    @app.post("/api/aprs/config")
    async def api_aprs_set_config(req: Request):
        body = await req.json()
        for k, v in body.items():
            if hasattr(aprs_runtime_cfg, k):
                setattr(aprs_runtime_cfg, k, v)
        if manager.aprs_is:
            await manager.start_aprs_is(aprs_runtime_cfg)  # restart with new config
        return aprs_runtime_cfg.__dict__

    @app.post("/api/aprs/beacon")
    async def api_aprs_beacon(req: Request):
        body = await req.json()
        lat = float(body.get("lat", aprs_runtime_cfg.filter_lat))
        lon = float(body.get("lon", aprs_runtime_cfg.filter_lon))
        altitude = int(body.get("altitude", 0))
        symbol = body.get("symbol", "/>")
        comment = body.get("comment", "SkyWatch SDR Monitor")
        line = build_position_beacon(
            callsign=aprs_runtime_cfg.callsign, ssid=aprs_runtime_cfg.ssid,
            symbol=symbol, lat=lat, lon=lon, altitude_ft=altitude, comment=comment,
        )
        ok = await (manager.aprs_is.send(line) if manager.aprs_is else asyncio.sleep(0, result=False))
        return {"ok": bool(ok), "line": line}

    @app.post("/api/aprs/message")
    async def api_aprs_message(req: Request):
        body = await req.json()
        to = (body.get("to") or "").strip().upper()
        text = body.get("text", "")
        msg_id = body.get("id", "")
        if not to or not text:
            raise HTTPException(400, "missing 'to' or 'text'")
        line = build_message(
            from_callsign=aprs_runtime_cfg.callsign, ssid=aprs_runtime_cfg.ssid,
            to_callsign=to, text=text, msg_id=msg_id,
        )
        ok = await (manager.aprs_is.send(line) if manager.aprs_is else asyncio.sleep(0, result=False))
        return {"ok": bool(ok), "line": line}

    @app.post("/api/aprs/status")
    async def api_aprs_status(req: Request):
        body = await req.json()
        status_text = body.get("status", "")
        if not status_text:
            raise HTTPException(400, "missing 'status'")
        line = build_status(
            callsign=aprs_runtime_cfg.callsign, ssid=aprs_runtime_cfg.ssid,
            status=status_text,
        )
        ok = await (manager.aprs_is.send(line) if manager.aprs_is else asyncio.sleep(0, result=False))
        return {"ok": bool(ok), "line": line}

    @app.post("/api/aprs/passcode")
    async def api_aprs_passcode(req: Request):
        body = await req.json()
        cs = (body.get("callsign") or "").strip().upper()
        if not cs:
            raise HTTPException(400, "missing 'callsign'")
        return {"callsign": cs, "passcode": compute_passcode(cs)}

    # ---- NOAA ----

    @app.get("/api/noaa/passes")
    async def api_noaa_passes():
        return [p.to_json() for p in manager.noaa_tracker.passes()]

    @app.get("/api/noaa/satellites")
    async def api_noaa_satellites():
        return [p.to_json() for p in manager.noaa_tracker.positions()]

    @app.get("/api/noaa/captures")
    async def api_noaa_captures():
        return [c.__dict__ for c in manager.captures()]

    @app.post("/api/noaa/capture")
    async def api_noaa_capture(req: Request):
        body = await req.json()
        sat = body.get("satellite", "")
        freq = float(body.get("frequency", 0))
        duration = int(body.get("duration", 900))
        if not sat or not freq:
            raise HTTPException(400, "missing satellite/frequency")
        result = await manager.capture_apt(sat, freq, duration)
        return result.__dict__

    # ---- NWR ----

    @app.get("/api/noaa/radio/status")
    async def api_nwr_status():
        s = manager.nwr.status
        return s.__dict__

    @app.post("/api/noaa/radio/start")
    async def api_nwr_start(req: Request):
        body = await req.json()
        freq = float(body.get("frequency", 162.4))
        device = int(body.get("device", 0))
        try:
            await manager.start_nwr(freq, device)
        except DeviceBusy as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"ok": True}

    @app.post("/api/noaa/radio/stop")
    async def api_nwr_stop():
        await manager.stop_nwr()
        return {"ok": True}

    @app.post("/api/noaa/radio/scan")
    async def api_nwr_scan(req: Request):
        body = await req.json()
        device = int(body.get("device", 0))
        results = await manager.nwr.scan(device)
        return [r.__dict__ for r in results]

    @app.get("/api/noaa/radio/stations")
    async def api_nwr_stations():
        return [t.to_json() for t in NWR_TRANSMITTERS]

    @app.get("/api/noaa/radio/stream")
    async def api_nwr_stream():
        return StreamingResponse(manager.nwr.stream(), media_type="audio/wav")

    # ---- Weather ----

    @app.get("/api/noaa/weather")
    async def api_weather(lat: Optional[float] = None, lon: Optional[float] = None,
                          state: str = "", wfo: str = ""):
        alerts = await fetch_alerts(lat=lat, lon=lon, state=state, wfo=wfo)
        forecast_periods = await fetch_forecast(lat, lon) if (lat is not None and lon is not None) else []
        # The dashboard expects the raw weather.gov shapes: alerts.features and
        # forecast.properties.periods. Re-wrap accordingly.
        return {
            "alerts": {"features": alerts},
            "forecast": {"properties": {"periods": forecast_periods}},
        }

    # ---- Config / API keys ----

    @app.get("/api/config/keys")
    async def api_keys_status():
        return {k: bool(v) for k, v in api_keys.items()}

    @app.post("/api/config/keys")
    async def api_keys_set(req: Request):
        body = await req.json()
        name = body.get("name", "")
        value = body.get("key", "")
        if not name:
            raise HTTPException(400, "missing 'name'")
        api_keys[name] = value
        _save_api_keys(api_keys)
        return {"ok": True}

    # ---- WebSocket ----

    @app.websocket("/ws")
    async def ws(ws: WebSocket):
        await ws.accept()
        await hub.add(ws)
        try:
            initial = await snapshot()
            await ws.send_text(json.dumps(initial))
            while True:
                # Just keep the connection alive — clients don't send.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await hub.remove(ws)

    # ---- Static frontend ----
    # The Go server embedded `static/` and served its subpaths from the root,
    # so index.html references /css, /js, /aprs-symbols without a prefix.
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")
    app.mount("/aprs-symbols", StaticFiles(directory=str(static_dir / "aprs-symbols")), name="aprs-symbols")

    @app.get("/")
    async def index():
        from fastapi.responses import FileResponse
        return FileResponse(str(static_dir / "index.html"))

    @app.get("/favicon.ico")
    async def favicon():
        from fastapi.responses import Response
        return Response(status_code=204)

    return app
