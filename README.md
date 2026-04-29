# 📡 SkyWatch

> A unified SDR monitoring dashboard. **Aircraft. Ships. Drones. Amateur radio. Weather satellites.** All on one map.

<p align="center">
  <img src="docs/screenshots/dashboard-vessels.png" alt="SkyWatch dashboard with live vessels" width="90%"/>
</p>

<table>
<tr>
<td align="center" width="33%">

### ✈️ Aircraft
RTL-SDR + `readsb`<br/>or OpenSky online

</td>
<td align="center" width="33%">

### 🚢 Ships
RTL-SDR + AIS-catcher<br/>or aisstream.io online

</td>
<td align="center" width="33%">

### 🛸 Drones
ASTM F3411 — WiFi<br/>+ Bluetooth LE

</td>
</tr>
<tr>
<td align="center">

### 📻 APRS
On-air via `rtl_fm` + `multimon-ng`<br/>or APRS-IS internet feed

</td>
<td align="center">

### 🛰️ NOAA Satellites
NOAA-15 / 18 / 19<br/>SGP4 + APT capture

</td>
<td align="center">

### 🌩️ NOAA Weather Radio
All 7 NWR channels<br/>live in your browser

</td>
</tr>
</table>

---

## 🚀 Quick start

> [!TIP]
> **Are you a beta tester?** Head straight to **[QUICKSTART.md](QUICKSTART.md)** — short, no jargon, no Python install, includes the Zadig driver step. The section below is for developers building from source.
>
> **Shipping a build to testers?** See **[DISTRIBUTION.md](DISTRIBUTION.md)**.

### One-click launch (developer mode)

| Platform | Command |
|---|---|
| 🪟 Windows | double-click `start.bat` |
| 🐧 Linux / 🍎 macOS | `./start.sh` |

The launcher creates a `.venv`, pip-installs everything from `requirements.txt`, and starts the server on `http://localhost:8080`. After the first run it skips the install step (only re-installs when `requirements.txt` changes), so it's also the everyday way to launch the app. Any flags you pass are forwarded — e.g. `start.bat -wifi wlan0`.

### Manual launch

```bash
pip install -r requirements.txt
python -m skywatch -addr :8080
```

Open **http://localhost:8080** → click ⚙ Settings → pick a module → **Start**.

> [!NOTE]
> **No hardware?** No problem. Click **Settings → Aircraft → Online (OpenSky)** and you'll see live aircraft the moment the map renders. APRS-IS, OpenSky, AISStream, and weather.gov all work without any radio.

---

## 🧰 What you can monitor

<details>
<summary><strong>✈️ Aircraft (ADS-B 1090 MHz)</strong></summary>

- **RF mode:** RTL-SDR dongle + a 1090 MHz antenna. Pure-Python decoder built in (no `readsb` install required) — `readsb` is supported as an alternative via `-readsb`.
- **Online mode:** OpenSky Network. Free tier rate-limited to ~400 calls/day; the dashboard polls only your visible map view to stretch the budget.
- **Database:** Aircraft type / registration / operator lookup. Importable from OpenSky in Settings.

</details>

<details>
<summary><strong>🚢 Ships (AIS 162 MHz)</strong></summary>

- **RF mode:** RTL-SDR + `rtl_ais` (Linux/macOS) or **AIS-catcher** (the Windows-friendly drop-in, pre-built binaries). Auto-detected at startup.
- **Online mode:** [aisstream.io](https://aisstream.io) WebSocket feed. Free API key needed.
- Ship name, type, MMSI country, dimensions, draught, ETA, destination — all parsed from AIS message types 1/2/3/5/18.

</details>

<details>
<summary><strong>🛸 Drone Remote ID (ASTM F3411)</strong></summary>

Catches drones broadcasting their identity and position. **Two independent radio bands**, either is enough to put a drone on the map:

- **📶 Bluetooth LE** — uses the host's built-in Bluetooth radio. **Just works**, catches DJI Mini 3/4 Pro, Mavic 3, Air 3, etc.
- **📡 WiFi monitor mode** — sniffs 802.11 beacons + probe-responses for the F3411 vendor IE. Requires Npcap + a chipset whose driver supports monitor mode. **Most laptop WiFi cards refuse** — see [SETUP.md §6](SETUP.md#6-drone-remote-id) for known-good adapters.

</details>

<details>
<summary><strong>📻 APRS (Amateur Packet Radio)</strong></summary>

Two independent receive paths plus an internet TX path:

- **APRS-IS** (internet) — `rotate.aprs2.net`, filtered by lat/lon/radius. Receive everywhere; transmit beacons / messages / status with your callsign + APRS-IS passcode.
- **APRS RF** (off-air) — `rtl_fm` + `multimon-ng` chain decodes Bell-202 AFSK1200 + HDLC + AX.25 from your RTL-SDR on 144.390 MHz (US) / 144.800 MHz (EU). See [SETUP.md §6.5](SETUP.md#65-aprs-rf-rtl_fm--multimon-ng).
- Stations are tagged in the UI with their source (🌐 IS / 📡 RF) so you can tell internet-relayed packets from ones you actually heard.

</details>

<details>
<summary><strong>🛰️ NOAA Weather Satellites</strong></summary>

- **Tracking:** SGP4 + Celestrak TLEs. Predicts NOAA-15 / 18 / 19 passes for your observer location.
- **APT capture:** RTL-SDR + `rtl_fm` records the 137 MHz transmission, recovers sync, and renders the grayscale image. Geometric correction (Doppler / earth-curvature) is on the roadmap.

</details>

<details>
<summary><strong>🌩️ NOAA Weather Radio + weather.gov</strong></summary>

- **NWR live audio** — listen to all 7 NWR channels (162.4 – 162.55 MHz) directly in the browser. Scan all 7 with one click.
- **NWR transmitter map** — every NWR transmitter location overlaid on the map.
- **weather.gov** — pulls active alerts and forecasts for the visible map area.

</details>

---

## 📦 What runs where

| Capability | 🐧 Linux | 🍎 macOS | 🪟 Windows |
|---|:---:|:---:|:---:|
| ADS-B (RF) | ✅ | ✅ | ✅ (WinUSB via Zadig) |
| AIS (RF) | ✅ | ✅ | ✅ (WinUSB via Zadig) |
| OpenSky / aisstream.io | ✅ | ✅ | ✅ |
| NOAA satellite tracking | ✅ | ✅ | ✅ |
| NOAA APT capture (`rtl_fm`) | ✅ | ✅ | ✅ |
| NOAA Weather Radio (`rtl_fm`) | ✅ | ✅ | ✅ |
| Drone RID — Bluetooth LE | ✅ | ✅ | ✅ |
| Drone RID — WiFi monitor mode | ✅ | ✅ * | ⚠️ Npcap **and** a compatible chipset — see [§6](SETUP.md#6-drone-remote-id) |
| APRS-IS gateway | ✅ | ✅ | ✅ |
| APRS RF (`rtl_fm` + `multimon-ng`) | ✅ | ✅ | ✅ |
| weather.gov forecasts/alerts | ✅ | ✅ | ✅ |

<sub>* macOS WiFi monitor mode requires a compatible USB adapter; built-in Apple silicon WiFi is locked.</sub>

---

## 🗺️ How online feeds bound their queries

The dashboard sends the visible map bounds with every `/api/start` and on every pan/zoom (debounced **500 ms** for ADS-B, **2 s** for AIS). OpenSky polls only that bounding box, clamped to its 20°×30° free-tier limit. AISStream re-subscribes only when the box has shifted by ≥0.5° (the same threshold the original Go version used to avoid spamming aisstream.io with rapid resubs).

---

## 🚦 CLI flags

Run `python -m skywatch -h` for the full list. Defaults match the Go version.

<details>
<summary><strong>Show all flags</strong></summary>

| Flag | Default | Purpose |
|------|---------|---------|
| `-addr` | `:8080` | Dashboard listen address (binds to 127.0.0.1 by default — use `-addr 0.0.0.0:8080` for LAN) |
| `-readsb` | `readsb` | Path to readsb binary |
| `-rtl-ais` | `rtl_ais` | Path to rtl_ais binary |
| `-aisstream-key` | (empty) | aisstream.io API key (auto-starts AIS online feed) |
| `-adsb-device` | `-1` | Auto-start ADS-B on RTL-SDR index N |
| `-ais-device` | `-1` | Auto-start AIS on RTL-SDR index N |
| `-wifi` | (empty) | WiFi adapter for drone-RID |
| `-monitor` | `true` | Auto-enable monitor mode |
| `-channel` | `6` | WiFi channel (0 = hop 1/6/11) |
| `-aprs-is` | `false` | Auto-connect to APRS-IS internet feed |
| `-aprs-call` | `N0CALL` | Callsign |
| `-aprs-ssid` | `9` | SSID |
| `-aprs-pass` | `-1` | Passcode (-1 = receive only) |
| `-aprs-lat` / `-aprs-lon` / `-aprs-radius` | 0 / 0 / 150 | Filter center + radius (km) |
| `-aprs-freq` | `144.390` | RF freq (US=144.390, EU=144.800) |
| `-aprs-beacon` | `false` | Enable position beacon |
| `-aprs-interval` | `10m` | Beacon interval |

</details>

---

## 🏗️ Architecture

```
┌──────────────┐   subprocess   ┌──────────────┐
│   readsb     │── SBS:30003 ──▶│              │
└──────────────┘                │              │
┌──────────────┐   subprocess   │              │
│ AIS-catcher  │── NMEA:10110 ─▶│              │
└──────────────┘                │              │
┌──────────────┐  rtl_fm |      │              │
│ APRS RF      │  multimon-ng ─▶│   tracker    │──▶  FastAPI + WebSocket
└──────────────┘                │   + APRS     │      localhost:8080
┌──────────────┐    scapy       │   store      │
│ WiFi monitor │── F3411 IE ───▶│              │
└──────────────┘                │              │
        OpenSky / aisstream     │              │
        APRS-IS / Celestrak     │              │
        weather.gov  ──────────▶└──────────────┘
```

<details>
<summary><strong>Project layout</strong></summary>

```
skywatch/
├── __main__.py        Entry point
├── cli.py             argparse — every flag the Go main.go had
├── tracker.py         Unified target store
├── sdr.py             RTL-SDR enumeration
├── adsb/              readsb + SBS parser, OpenSky, aircraft DB, classifier
├── ais/               rtl_ais + NMEA, aisstream.io, ship-type/MMSI tables
├── aprs/              IS gateway, RF decoder (rtl_fm | multimon-ng),
│                      parser (uncompressed + base-91 compressed),
│                      station + message store, beacon/message TX
├── noaa/              SGP4 tracker, APT capture, NWR weather radio,
│                      weather.gov client
├── remoteid/          scapy WiFi sniffer + ASTM F3411 parser
├── web/
│   ├── server.py      FastAPI app + REST routes + WebSocket
│   ├── manager.py     Module lifecycle
│   └── static/        Dashboard (HTML + Leaflet + plain JS)
└── util/geo.py        Bounding-box helpers
```

</details>

---

## 🔬 Origins & lineage

This is a Python rewrite of the previous Go implementation (preserved on the [`go-rewrite`](https://github.com/District47/SkyWatch/tree/go-rewrite) branch) and the original PyQt build (preserved on [`pyqt-archive`](https://github.com/District47/SkyWatch/tree/pyqt-archive)).

> [!IMPORTANT]
> Every CLI flag, REST route, WebSocket message shape, dialed-in RF constant, and timeout matches the Go version — so existing setups keep working.

| Branch | Contents |
|---|---|
| `main` | This Python rewrite (current) |
| `go-rewrite` | Previous Go implementation |
| `pyqt-archive` | Original PyQt desktop build |

---

## 🚧 What's deferred to v2

The Go version had a few subsystems that are heavier ports. Their web API surfaces work — the dashboard just doesn't get RF-side decodes from these yet:

- **APRS UV-Pro Bluetooth TNC.** TX path through APRS-IS works; UV-Pro KISS framing is stubbed.
- **APT image geometric correction.** Capture + sync detection + grayscale image work; Doppler / earth-curvature correction is on the roadmap.

> [!NOTE]
> **APRS RF demod was on this list — it's now shipping.** Bell-202 AFSK + HDLC + AX.25 decoded via the `rtl_fm | multimon-ng` chain. See [SETUP.md §6.5](SETUP.md#65-aprs-rf-rtl_fm--multimon-ng).

---

## 📜 License

MIT.
