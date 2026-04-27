# SkyWatch (Python)

Unified SDR monitoring tool — tracks **aircraft** (ADS-B), **ships** (AIS), **drones** (Remote ID), and amateur **APRS** stations, plus receives **NOAA** weather satellites and weather radio. Real-time map dashboard at `http://localhost:8080`.

This is a 1:1 Python port of the Go implementation on the `go-rewrite` branch. All CLI flags, REST routes, WebSocket message shapes, dialed-in RF constants, and timeouts match the Go version so existing setups keep working.

## What runs where

| Capability | Linux | macOS | Windows |
|---|---|---|---|
| ADS-B (`readsb` + RTL-SDR) | ✅ | ✅ | ✅ (with WinUSB driver via Zadig) |
| AIS (`rtl_ais` + RTL-SDR) | ✅ | ✅ | ✅ (with WinUSB driver via Zadig) |
| OpenSky / aisstream.io online feeds | ✅ | ✅ | ✅ |
| NOAA satellite tracking (SGP4) | ✅ | ✅ | ✅ |
| NOAA APT image capture (`rtl_fm`) | ✅ | ✅ | ✅ |
| NOAA Weather Radio (`rtl_fm`) | ✅ | ✅ | ✅ |
| Drone Remote ID (WiFi monitor mode) | ✅ | ✅ (compatible USB adapter) | ✅ (Npcap + compatible USB adapter, e.g. Alfa AWUS036ACH/NHA) |
| APRS-IS gateway | ✅ | ✅ | ✅ |
| weather.gov forecasts/alerts | ✅ | ✅ | ✅ |

## Quick start

```bash
# from the project root (C:\Users\Owner\projects\SkyWatch-py on Windows)
pip install -r requirements.txt
python -m skywatch -addr :8080
```

PowerShell one-liner:

```powershell
cd C:\Users\Owner\projects\SkyWatch-py; pip install -r requirements.txt; if ($?) { python -m skywatch -addr :8080 }
```

Open `http://localhost:8080` and use the dashboard to start modules. Or auto-start everything via flags:

```bash
# 2 RTL-SDR dongles + WiFi adapter for drone-RID
python -m skywatch -adsb-device 0 -ais-device 1 -wifi wlan0

# Online-only (no hardware) — uses OpenSky + aisstream
python -m skywatch -aisstream-key YOURKEY
```

See [SETUP.md](SETUP.md) for OS-specific install instructions (RTL-SDR drivers, `readsb`, `rtl_ais`, `rtl_fm`, Npcap on Windows, monitor mode).

## CLI flags

Identical to the Go version. Run `python -m skywatch -h` for the full list.

| Flag | Default | Purpose |
|------|---------|---------|
| `-addr` | `:8080` | dashboard listen address |
| `-readsb` | `readsb` | path to readsb binary |
| `-rtl-ais` | `rtl_ais` | path to rtl_ais binary |
| `-aisstream-key` | (empty) | aisstream.io API key |
| `-adsb-device` | `-1` | auto-start ADS-B on RTL-SDR index |
| `-ais-device` | `-1` | auto-start AIS on RTL-SDR index |
| `-wifi` | (empty) | WiFi interface for drone-RID |
| `-monitor` | `true` | auto-enable monitor mode |
| `-channel` | `6` | WiFi channel (0 = hop 1/6/11) |
| `-aprs-is` | `false` | enable APRS-IS gateway |
| `-aprs-call` | `N0CALL` | callsign |
| `-aprs-ssid` | `9` | SSID |
| `-aprs-pass` | `-1` | passcode (-1 = receive only) |
| `-aprs-lat` / `-aprs-lon` / `-aprs-radius` | 0 / 0 / 150 | filter center + radius (km) |
| `-aprs-freq` | `144.390` | RF freq (US=144.390 / EU=144.800) |
| `-aprs-beacon` | `false` | enable position beacon |
| `-aprs-interval` | `10m` | beacon interval |

## What's deferred to v2

The Go version has a few subsystems that are heavier ports and still ship as v0 stubs here. The web API surface for these still works — the dashboard just won't get RF-side decodes until they land:

- **APRS RF demod** (Bell-202 AFSK + HDLC + AX.25) — IS-gateway path is fully working; an RTL-SDR-based packet receiver is the next module.
- **APRS UV-Pro Bluetooth TNC** — TX path through APRS-IS works; UV-Pro KISS framing is stubbed.
- **APT image geometric correction** — capture + sync detection + grayscale image work; Doppler / earth-curvature correction is on the roadmap.

## Architecture

```
┌──────────┐   subprocess  ┌─────────────┐
│ readsb   │──SBS:30003──▶ │             │
└──────────┘               │             │
┌──────────┐   subprocess  │             │
│ rtl_ais  │──NMEA:10110─▶ │             │
└──────────┘               │             │
┌──────────┐    scapy      │   tracker   │──▶ FastAPI + WebSocket
│ WiFi mon │──ASTM F3411─▶ │   + APRS    │     localhost:8080
└──────────┘               │   store     │
       OpenSky / aisstream │             │
       APRS-IS / Celestrak │             │
       weather.gov         └─────────────┘
```
