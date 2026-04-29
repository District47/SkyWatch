# SkyWatch

Unified SDR monitoring tool — tracks **aircraft** (ADS-B), **ships** (AIS), **drones** (Remote ID), and amateur **APRS** stations, plus receives **NOAA** weather satellites and weather radio. Real-time map dashboard at `http://localhost:8080`.

![Dashboard with vessels and detail panel](docs/screenshots/dashboard-vessels.png)
![Aircraft view with OpenSky online feed](docs/screenshots/dashboard-aircraft.png)
![Status bar](docs/screenshots/status-bar.png)

This is a Python port of the previous Go implementation (preserved on the [`go-rewrite`](https://github.com/District47/SkyWatch/tree/go-rewrite) branch) and the original PyQt build (preserved on [`pyqt-archive`](https://github.com/District47/SkyWatch/tree/pyqt-archive)). All CLI flags, REST routes, WebSocket message shapes, dialed-in RF constants, and timeouts match the Go version so existing setups keep working.

## What it does

- **ADS-B** — track aircraft via `readsb` + RTL-SDR, or pull live data from the OpenSky Network with no hardware required.
- **AIS** — track vessels via `rtl_ais` + RTL-SDR, or live from aisstream.io.
- **Drone Remote ID** — sniff WiFi beacons / probe-responses for the ASTM F3411 vendor-specific IE (drones broadcasting their position over WiFi).
- **APRS** — receive packets two ways: over the internet via APRS-IS, or off-air on 144.390 MHz (US) via RTL-SDR + `rtl_fm` + `multimon-ng`. View stations / messages on the map; transmit beacons, messages, and status through APRS-IS with your callsign + passcode.
- **NOAA satellites** — predict NOAA-15/18/19 passes (SGP4 + Celestrak TLEs) and capture APT imagery via `rtl_fm` + RTL-SDR.
- **NOAA Weather Radio** — listen to NWR (162.4–162.55 MHz) live in the browser, scan all 7 channels, see all transmitter locations.
- **weather.gov** — pull active alerts and forecasts for the visible area.

The dashboard is one page; tabs on the right side filter the map and right pane to All / Aircraft / Vessels / Drones / APRS / NOAA. Clicking a target shows its full record.

## What runs where

| Capability | Linux | macOS | Windows |
|---|---|---|---|
| ADS-B (`readsb` + RTL-SDR) | yes | yes | yes (WinUSB driver via Zadig) |
| AIS (`rtl_ais` + RTL-SDR) | yes | yes | yes (WinUSB driver via Zadig) |
| OpenSky / aisstream.io online feeds | yes | yes | yes |
| NOAA satellite tracking (SGP4) | yes | yes | yes |
| NOAA APT image capture (`rtl_fm`) | yes | yes | yes |
| NOAA Weather Radio (`rtl_fm`) | yes | yes | yes |
| Drone Remote ID — **WiFi monitor mode** | yes | yes (compatible USB adapter) | yes — **requires [Npcap](https://npcap.com/) AND a chipset whose driver supports monitor mode** (e.g. Alfa AWUS036NHA / AR9271). Most generic / built-in WiFi cards will NOT work. See [SETUP.md §6](SETUP.md#6-drone-remote-id). |
| Drone Remote ID — **Bluetooth LE** | yes | yes | yes — uses host Bluetooth, no extra hardware. Catches DJI broadcasts. |
| APRS-IS gateway | yes | yes | yes |
| APRS RF (`rtl_fm` + `multimon-ng` + RTL-SDR) | yes | yes | yes (drop binaries into `tools/win64/` — see [SETUP.md §6.5](SETUP.md#65-aprs-rf-rtl_fm--multimon-ng)) |
| weather.gov forecasts/alerts | yes | yes | yes |

## Quick start

> **Beta tester?** You probably want [QUICKSTART.md](QUICKSTART.md) — short, no jargon, no Python install, includes the Zadig step. The section below is for developers building from source.
>
> **Shipping a build to testers?** See [DISTRIBUTION.md](DISTRIBUTION.md).

**Easiest path — one click / one command:**

| Platform | Command |
|---|---|
| Windows | double-click `start.bat` (or `start.bat` from cmd) |
| Linux / macOS | `./start.sh` |

The launcher creates a `.venv`, installs everything from `requirements.txt`, and starts the server on `http://localhost:8080`. On subsequent runs it skips install (only re-runs pip when `requirements.txt` changes), so it's also the everyday way to launch the app. Any flags you pass are forwarded — e.g. `start.bat -wifi wlan0`.

**Manual (no launcher):**

```bash
pip install -r requirements.txt
python -m skywatch -addr :8080
```

Open `http://localhost:8080`. From the dashboard:

- Click **Settings → Aircraft** and pick a source. **Online (OpenSky)** needs no hardware — pan/zoom the map first, then click **Start** and only aircraft in your visible area will be polled (every 10 s, free-tier rate-limited).
- **Vessels** works the same way: choose **Online (AISStream)** after saving an aisstream.io key in **Settings → API Keys**, or pick an RTL-SDR device for `rtl_ais`.
- **NOAA** tab has Listen / Scan All for weather radio and a satellite capture launcher.

To auto-start everything via flags:

```bash
# 2 RTL-SDR dongles + WiFi adapter for drone-RID
python -m skywatch -adsb-device 0 -ais-device 1 -wifi wlan0

# Online-only (no hardware)
python -m skywatch -aisstream-key YOURKEY
```

See [SETUP.md](SETUP.md) for OS-specific install steps (RTL-SDR drivers, `readsb`, `rtl_ais`, `rtl_fm`, Npcap).

## How online feeds bound their queries

The dashboard sends the visible map bounds with the `/api/start` request and on every pan/zoom (debounced 500 ms for ADS-B, 2 s for AIS). OpenSky polls only that bounding box, clamped to its 20°×30° free-tier limit. AISStream re-subscribes only when the box has shifted by ≥0.5° (the same threshold the Go version used to avoid spamming aisstream.io with rapid resubs).

## CLI flags

Run `python -m skywatch -h` for the full list. Defaults match the Go version.

| Flag | Default | Purpose |
|------|---------|---------|
| `-addr` | `:8080` | dashboard listen address (binds to 127.0.0.1 by default — use `-addr 0.0.0.0:8080` for LAN access) |
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

## Project layout

```
skywatch/
├── __main__.py        entry point
├── cli.py             argparse — all flags from the Go main
├── tracker.py         unified target store
├── sdr.py             RTL-SDR enumeration
├── adsb/              readsb + SBS parser, OpenSky, aircraft DB, classifier
├── ais/               rtl_ais + NMEA, aisstream.io, ship-type/MMSI tables
├── aprs/              IS gateway, parser (uncompressed + base-91 compressed),
│                      station + message store, beacon/message TX
├── noaa/              SGP4 tracker, APT capture, NWR weather radio,
│                      weather.gov client
├── remoteid/          scapy WiFi sniffer + ASTM F3411 parser
├── web/
│   ├── server.py      FastAPI app + REST routes + WebSocket
│   ├── manager.py     module lifecycle
│   └── static/        dashboard (HTML + Leaflet + custom JS)
└── util/geo.py        bounding-box helpers
```

## What's deferred to v2

The Go version has a few subsystems that are heavier ports and still ship as v0 stubs here. The web API surface for these works — the dashboard just won't get RF-side decodes until they land:

- **APRS UV-Pro Bluetooth TNC.** TX path through APRS-IS works; UV-Pro KISS framing is stubbed.
- **APT image geometric correction.** Capture + sync detection + grayscale image work; Doppler / earth-curvature correction is on the roadmap.

## Branches

| Branch | Contents |
|---|---|
| `main` | This Python rewrite (current). |
| `go-rewrite` | Previous Go implementation. |
| `pyqt-archive` | Original PyQt desktop build. |

## License

MIT.
