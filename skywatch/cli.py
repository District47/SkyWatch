"""Command-line argument parsing. Flags mirror cmd/skywatch/main.go exactly.

All defaults preserved so existing invocations from the Go version continue to
work. Times are accepted as Go-style durations (e.g. "10m", "30s") for parity.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass


_DUR_RE = re.compile(r"^\s*(\d+)\s*(ms|s|m|h)?\s*$")


def parse_duration(s: str) -> float:
    """Parse a Go-style duration string to seconds. e.g. '10m' -> 600.0."""
    m = _DUR_RE.match(s)
    if not m:
        try:
            return float(s)
        except ValueError as e:
            raise argparse.ArgumentTypeError(f"invalid duration: {s!r}") from e
    n = int(m.group(1))
    unit = (m.group(2) or "s").lower()
    return {"ms": n / 1000.0, "s": float(n), "m": n * 60.0, "h": n * 3600.0}[unit]


@dataclass
class Args:
    addr: str
    readsb: str
    rtl_ais: str
    ais_catcher: str
    aisstream_key: str
    wifi: str
    monitor: bool
    channel: int
    adsb_device: int
    ais_device: int
    aprs_is: bool
    aprs_call: str
    aprs_ssid: int
    aprs_pass: int
    aprs_lat: float
    aprs_lon: float
    aprs_radius: int
    aprs_sdr_device: int
    aprs_freq: float
    aprs_uvpro: str
    aprs_beacon: bool
    aprs_interval: float
    aprs_symbol: str
    aprs_comment: str
    version: bool


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skywatch",
        description="Unified SDR monitoring (ADS-B aircraft, AIS vessels, drones, APRS, NOAA weather).",
    )
    p.add_argument("-addr", default=":8080", help="web dashboard listen address (default :8080)")
    p.add_argument("-readsb", default="readsb", help="path to readsb binary (default 'readsb')")
    p.add_argument("-rtl-ais", dest="rtl_ais", default="rtl_ais", help="path to rtl_ais binary")
    p.add_argument("-ais-catcher", dest="ais_catcher", default="AIS-catcher",
                   help="path to AIS-catcher binary (Windows-friendly fallback if rtl_ais is missing)")
    p.add_argument("-aisstream-key", dest="aisstream_key", default="", help="aisstream.io API key (enables online AIS)")
    p.add_argument("-wifi", default="", help="WiFi interface for drone Remote ID (e.g. wlan0)")
    p.add_argument("-monitor", default="true", help="auto-enable WiFi monitor mode (true/false)")
    p.add_argument("-channel", type=int, default=6, help="WiFi channel (0 = hop 1,6,11)")
    p.add_argument("-adsb-device", dest="adsb_device", type=int, default=-1, help="auto-start ADS-B on RTL-SDR device index (-1 = manual)")
    p.add_argument("-ais-device", dest="ais_device", type=int, default=-1, help="auto-start AIS on RTL-SDR device index (-1 = manual)")
    # APRS
    p.add_argument("-aprs-is", dest="aprs_is", default="false", help="enable APRS-IS internet feed")
    p.add_argument("-aprs-call", dest="aprs_call", default="N0CALL", help="APRS callsign")
    p.add_argument("-aprs-ssid", dest="aprs_ssid", type=int, default=9, help="APRS SSID (0-15)")
    p.add_argument("-aprs-pass", dest="aprs_pass", type=int, default=-1, help="APRS-IS passcode (-1 = receive only)")
    p.add_argument("-aprs-lat", dest="aprs_lat", type=float, default=0.0, help="APRS-IS filter center latitude")
    p.add_argument("-aprs-lon", dest="aprs_lon", type=float, default=0.0, help="APRS-IS filter center longitude")
    p.add_argument("-aprs-radius", dest="aprs_radius", type=int, default=150, help="APRS-IS filter radius (km)")
    p.add_argument("-aprs-sdr-device", dest="aprs_sdr_device", type=int, default=-1, help="auto-start APRS RF on RTL-SDR device")
    p.add_argument("-aprs-freq", dest="aprs_freq", type=float, default=144.390, help="APRS RF frequency (MHz, US=144.390 / EU=144.800)")
    p.add_argument("-aprs-uvpro", dest="aprs_uvpro", default="", help="UV-Pro Bluetooth serial device (e.g. /dev/rfcomm0)")
    p.add_argument("-aprs-beacon", dest="aprs_beacon", default="false", help="enable APRS-IS position beacon (true/false)")
    p.add_argument("-aprs-interval", dest="aprs_interval", type=parse_duration, default=600.0, help="beacon interval (e.g. 10m)")
    p.add_argument("-aprs-symbol", dest="aprs_symbol", default="/>", help="APRS symbol (2 chars)")
    p.add_argument("-aprs-comment", dest="aprs_comment", default="SkyWatch SDR Monitor", help="beacon comment")
    p.add_argument("-version", default=False, action="store_true", help="print version and exit")
    return p


def _to_bool(s) -> bool:
    if isinstance(s, bool):
        return s
    return str(s).strip().lower() in ("1", "true", "yes", "y", "on")


def parse(argv: list[str] | None = None) -> Args:
    ns = build_parser().parse_args(argv)
    return Args(
        addr=ns.addr,
        readsb=ns.readsb,
        rtl_ais=ns.rtl_ais,
        ais_catcher=ns.ais_catcher,
        aisstream_key=ns.aisstream_key,
        wifi=ns.wifi,
        monitor=_to_bool(ns.monitor),
        channel=ns.channel,
        adsb_device=ns.adsb_device,
        ais_device=ns.ais_device,
        aprs_is=_to_bool(ns.aprs_is),
        aprs_call=ns.aprs_call,
        aprs_ssid=ns.aprs_ssid,
        aprs_pass=ns.aprs_pass,
        aprs_lat=ns.aprs_lat,
        aprs_lon=ns.aprs_lon,
        aprs_radius=ns.aprs_radius,
        aprs_sdr_device=ns.aprs_sdr_device,
        aprs_freq=ns.aprs_freq,
        aprs_uvpro=ns.aprs_uvpro,
        aprs_beacon=_to_bool(ns.aprs_beacon),
        aprs_interval=ns.aprs_interval,
        aprs_symbol=ns.aprs_symbol,
        aprs_comment=ns.aprs_comment,
        version=ns.version,
    )
