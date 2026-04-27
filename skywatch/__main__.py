"""SkyWatch entry point.

Mirrors cmd/skywatch/main.go: parses flags, wires modules into the manager,
auto-starts whatever was requested via flags, then serves the dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

from . import __version__
from .cli import parse, Args
from .tracker import Tracker
from .aprs import APRSStore, APRSISConfig
from .alerts import AlertManager
from .web.manager import Manager
from .web.server import build_app

log = logging.getLogger("skywatch")


def _split_addr(addr: str) -> tuple[str, int]:
    if addr.startswith(":"):
        return ("127.0.0.1", int(addr[1:]))
    host, _, port = addr.rpartition(":")
    return (host or "127.0.0.1", int(port or 8080))


async def _bootstrap(args: Args, manager: Manager) -> None:
    # Auto-start ADS-B if a device index was provided.
    if args.adsb_device >= 0:
        try:
            await manager.start_adsb(device=args.adsb_device, readsb_path=args.readsb)
        except Exception as e:
            log.warning("auto-start ADS-B failed: %s", e)

    # Auto-start AIS if a device index was provided.
    if args.ais_device >= 0:
        try:
            await manager.start_ais(device=args.ais_device, rtl_ais_path=args.rtl_ais)
        except Exception as e:
            log.warning("auto-start AIS failed: %s", e)

    # aisstream.io online feed.
    if args.aisstream_key:
        try:
            await manager.start_aisstream(api_key=args.aisstream_key)
        except Exception as e:
            log.warning("auto-start aisstream failed: %s", e)

    # Drone Remote ID.
    if args.wifi:
        try:
            await manager.start_remoteid(args.wifi, args.monitor, args.channel)
        except Exception as e:
            log.warning("auto-start remoteid failed: %s", e)

    # NOAA satellite tracker (always on; uses (0,0) until UI sets observer).
    try:
        await manager.start_noaa_tracker(0.0, 0.0)
    except Exception as e:
        log.warning("noaa tracker start failed: %s", e)

    # APRS-IS gateway.
    if args.aprs_is:
        cfg = APRSISConfig(
            callsign=args.aprs_call, ssid=args.aprs_ssid, passcode=args.aprs_pass,
            filter_lat=args.aprs_lat, filter_lon=args.aprs_lon,
            filter_radius_km=args.aprs_radius,
        )
        try:
            await manager.start_aprs_is(cfg)
        except Exception as e:
            log.warning("auto-start APRS-IS failed: %s", e)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    if args.version:
        print(f"skywatch {__version__}")
        return 0

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tracker = Tracker()
    aprs_store = APRSStore()
    alerts = AlertManager(tracker)
    manager = Manager(tracker, aprs_store)

    static_dir = Path(__file__).parent / "web" / "static"
    app = build_app(tracker=tracker, aprs_store=aprs_store, manager=manager,
                    alerts=alerts, static_dir=static_dir, args=args)

    @app.on_event("startup")
    async def _bootstrap_modules() -> None:
        await _bootstrap(args, manager)

    host, port = _split_addr(args.addr)
    log.info("SkyWatch %s listening on http://%s:%d", __version__, host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
