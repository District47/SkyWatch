# Setup — SkyWatch (Python)

SkyWatch is pure Python, but to use real RTL-SDR and WiFi hardware it shells out to platform-native binaries. This guide walks through every prerequisite per OS, with verification commands.

If you only want online feeds (OpenSky aircraft + aisstream.io vessels + APRS-IS + weather alerts), you can skip everything in §3–§7 and just install Python deps (§1).

## Quick path: bundled `tools/` folder

If you populate `tools/<platform>/` inside the project (see [tools/README.md](tools/README.md)), SkyWatch auto-prepends it to PATH and to the Windows DLL search at startup. **No system install of librtlsdr / AIS-catcher / rtl_fm required.** Drop the binaries into `tools/win64/` once and the whole repo becomes a self-contained shippable folder. Verify with:

```bash
python -c "from skywatch._bootstrap import BUNDLED_TOOLS_DIR; print(BUNDLED_TOOLS_DIR)"
```

The rest of this document covers the system-install path for users who prefer that.

---

## 1. Python (all OSes)

Python ≥ 3.10. Then:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Verify:

```bash
python -m skywatch -version
```

Run the server:

```bash
python -m skywatch -addr :8080
```

Open `http://localhost:8080`. With nothing else installed you'll get an empty dashboard — go to **Settings → Aircraft → Online (OpenSky)** and click **Start** to see live aircraft with no hardware.

PowerShell one-liner (Windows):

```powershell
cd C:\Users\Owner\projects\SkyWatch-py
pip install -r requirements.txt
python -m skywatch -addr :8080
```

---

## 2. RTL-SDR USB driver

Required for **ADS-B**, **AIS**, and **NOAA Weather Radio** (anything that needs an RTL-SDR dongle). Skip if you're only using online feeds.

### Windows — Zadig (one-time)

1. Plug in your RTL-SDR dongle.
2. Download **Zadig**: https://zadig.akeo.ie/
3. **Options → List All Devices**.
4. Pick **Bulk-In, Interface (Interface 0)** for the dongle.
5. Target driver: **WinUSB**, click **Replace Driver**.

Verify:

```powershell
python -c "from rtlsdr import RtlSdr; print('devices =', RtlSdr.get_device_count())"
```

Should print `devices = 1` (or however many you have plugged in). If it prints `0`, Zadig didn't replace the right interface — repeat step 3-5.

### macOS

```bash
brew install librtlsdr
```

### Linux (Debian / Ubuntu)

```bash
sudo apt install librtlsdr-dev rtl-sdr

# Blacklist the kernel DVB driver so RTL-SDR works for SDR
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf

# Allow non-root access (replug the dongle after this)
sudo udevadm control --reload-rules
```

---

## 3. ADS-B — `readsb`

Required to spawn an RTL-SDR-driven 1090 MHz decoder. Not needed for the OpenSky online feed.

### macOS / Linux — build from source

```bash
git clone https://github.com/wiedehopf/readsb /tmp/readsb
cd /tmp/readsb && make RTLSDR=yes
sudo cp readsb /usr/local/bin/
```

### Windows

Easiest path: build via **WSL2** Ubuntu (same commands as Linux above) and run SkyWatch inside WSL.

Or use a community pre-built binary if you find a trusted one. Place `readsb.exe` somewhere on PATH (e.g. `C:\Tools\rtl-sdr\`), then add that folder to your system PATH.

Verify:

```bash
readsb --help
```

---

## 4. AIS — `rtl_ais` or AIS-catcher

Required to drive an RTL-SDR at 162 MHz. Not needed for the aisstream.io online feed.

SkyWatch auto-detects which decoder is available — preferring `rtl_ais` if found, falling back to **AIS-catcher** otherwise. AIS-catcher is the easy choice on Windows because pre-built binaries are published.

### Windows — AIS-catcher (recommended)

1. Download the latest `AIS-catcher.x64.zip` from https://github.com/jvde-github/AIS-catcher/releases
2. Extract to `C:\tools\AIS-catcher\` (or anywhere on PATH).
3. Add to PATH (one-time):

```powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path","User") + ";C:\tools\AIS-catcher", "User")
```

Verify in a fresh PowerShell:

```powershell
where.exe AIS-catcher
AIS-catcher -h
```

### macOS / Linux — `rtl_ais`

```bash
git clone https://github.com/dgiardini/rtl-ais /tmp/rtl-ais
cd /tmp/rtl-ais && make
sudo cp rtl_ais /usr/local/bin/
```

Or use AIS-catcher on Linux/macOS too — it builds easily with the rtl-sdr dev headers.

Verify (whichever you installed):

```bash
rtl_ais --help    # OR
AIS-catcher -h
```

---

## 5. NOAA Weather Radio — `rtl_fm`

Used by the NWR Listen / Scan All buttons in the NOAA tab. Ships with the standard rtl-sdr toolchain.

### macOS

```bash
brew install librtlsdr   # rtl_fm is part of this
```

### Linux

```bash
sudo apt install rtl-sdr   # rtl_fm is part of this
```

### Windows

Download the **rtl-sdr-blog** Windows release: https://github.com/rtlsdrblog/rtl-sdr-blog/releases — extract `rtl_fm.exe` and put it on PATH.

Verify:

```bash
rtl_fm -h
```

---

## 6. Drone Remote ID

SkyWatch listens for drone Remote ID broadcasts on **two independent radio bands**. Each is set up separately, and a drone broadcasting on either is enough to put it on the map.

### 6.0 What gets you the most coverage

| Band | What you need | Hard or easy? |
|---|---|---|
| **Bluetooth LE** | The host's built-in Bluetooth radio (already on every laptop) | **Trivial** — works out of the box. Catches DJI Mini 3 / Mini 4 Pro / Mavic 3 / Air 3 etc. |
| **WiFi 802.11 monitor mode** | Npcap + a *specific* USB WiFi adapter (see below) | **Often a fight on Windows** — most adapters can't do it |

If you only want DJI drones, **BLE alone is usually enough** and you can skip the WiFi-monitor section entirely.

### 6.1 Npcap — REQUIRED on Windows for the WiFi path

The Windows kernel driver scapy uses for raw 802.11 capture. Without it, the WiFi sniffer cannot see any packets, period.

1. Download Npcap: https://npcap.com/#download
2. Run the installer. **Check both** boxes during install:
   - ✅ **"Support raw 802.11 traffic (and monitor mode) for wireless adapters"**
   - ✅ **"Install Npcap in WinPcap API-compatible Mode"**
3. Reboot.

Verify:

```powershell
python -c "from scapy.all import get_if_list; print(len(get_if_list()), 'interfaces')"
```

You should see no `WARNING: No libpcap provider available` and a non-empty list.

On Linux/macOS, libpcap ships with the OS — no separate install.

### 6.2 A WiFi adapter that *actually* supports monitor mode

> **⚠️ Not every WiFi adapter can do this.** Even with Npcap installed correctly, the host driver has to expose 802.11 monitor mode, and most consumer drivers (especially built-in laptop chipsets and cheap USB sticks) refuse. Buying a generic "USB WiFi" or relying on your laptop's internal card is the #1 reason WiFi RID doesn't work.

**Known-good adapters (Windows + Npcap):**

| Adapter | Chipset | Notes |
|---|---|---|
| **Alfa AWUS036NHA** | Atheros AR9271 | The reference choice. 2.4 GHz only, no Wi-Fi 6, but monitor mode is rock solid with no driver hacks. ~$30. |
| **Alfa AWUS036ACH / ACHM** | Realtek RTL8812AU | 2.4 + 5 GHz, monitor mode works **only with the morrownr driver**: https://github.com/morrownr/8812au-20210820 |
| **TP-Link TL-WN722N v1** | Atheros AR9271 | Same chip as the Alfa NHA — cheap and works. **Only the v1** — v2/v3 use a Realtek that won't monitor. |

**Known-bad adapters on Windows (despite the marketing):**

| Adapter | Chipset | Why it fails |
|---|---|---|
| **Alfa AWUS036AXML** | MediaTek MT7921AU | Wi-Fi 6 / 6E hardware, but the Windows driver only exposes client mode. Monitor mode is **broken** on Windows; works fine on Linux. |
| **Edimax N150 / EW-7811Un** | Realtek RTL8188 | Driver doesn't expose monitor mode at all. |
| Any built-in laptop WiFi | Intel / Killer / Broadcom / MediaTek | Monitor mode is locked off in the Windows driver. |
| **Anything using "Microsoft Wi-Fi Direct Virtual"** | (virtual adapter) | Not a real radio. |

If you need Wi-Fi 6 monitor mode, the realistic path on Windows is to install [usbipd-win](https://github.com/dorssel/usbipd-win) and pass the adapter through to **WSL2**, where the Linux driver supports it.

### 6.3 Verify drone scanning

On the **Drones** tab, pick your adapter from the dropdown and click **Start**. The status box reports both bands live:

```
WiFi sniff
  📡 Frames: <total raw 802.11 frames>
       mgmt: <beacons + probe-responses>
  🛸 Drone RID: <frames containing the ASTM F3411 vendor IE>
Bluetooth LE
  📶 Adv frames: <BLE advertisements seen>
  🛸 Drone RID: <BLE service-data frames with UUID 0xFFFA>
```

| What you see | Verdict |
|---|---|
| `Frames > 0`, `mgmt > 0` | WiFi monitor mode is working ✅ |
| `Frames > 0`, `mgmt = 0` | Adapter sniffing but not in monitor mode — driver/chipset limitation. Switch adapter or use BLE. |
| `Frames = 0` | Driver not loaded for the chipset, or wrong adapter selected. |
| `BLE Adv frames > 0` | BLE scanner is healthy ✅ — DJI broadcasts will land here. |

You can sanity-check the parser without flying anything by installing the **Open Drone ID** Android app, which broadcasts a synthetic RID over both bands.

---

## 7. Optional: API keys

### aisstream.io (online vessel feed)

Required if you want vessels via the **Online (AISStream)** option without an RTL-SDR.

1. Sign up: https://aisstream.io
2. Generate a free API key in the dashboard.
3. Open SkyWatch → top-right **Settings** → **API Keys** → paste under `aisstream` → **Save**.

### OpenSky Network (lifts the 400-call/day rate limit)

The dashboard works without an account, but anonymous OpenSky calls are capped at ~400/day. If you see HTTP 429 errors in the log:

1. Sign up: https://opensky-network.org
2. (HTTP basic-auth support not yet wired into SkyWatch — let me know if you want it and I'll add `OPENSKY_USERNAME`/`OPENSKY_PASSWORD` env-var support.)

---

## 8. CLI flags

All flags are listed in `python -m skywatch -h`. The dashboard can drive everything at runtime, so flags are optional and mostly useful for systemd / launchd unit files.

| Flag | Default | Purpose |
|------|---------|---------|
| `-addr` | `:8080` | dashboard listen address (binds to 127.0.0.1; use `0.0.0.0:8080` for LAN) |
| `-readsb` | `readsb` | path to readsb binary |
| `-rtl-ais` | `rtl_ais` | path to rtl_ais binary |
| `-aisstream-key` | (empty) | aisstream.io API key (auto-starts AIS online feed) |
| `-adsb-device` | `-1` | auto-start ADS-B on RTL-SDR index N |
| `-ais-device` | `-1` | auto-start AIS on RTL-SDR index N |
| `-wifi` | (empty) | WiFi adapter for drone-RID (use the dashboard dropdown instead — easier) |
| `-aprs-is` | `false` | auto-connect to APRS-IS internet feed |
| `-aprs-call` | `N0CALL` | callsign |
| `-aprs-pass` | `-1` | passcode (-1 = receive only) |

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `WARNING: No libpcap provider available` | Install Npcap (Windows) — see §6a. |
| OpenSky returning 0 aircraft | Free tier is rate-limited to ~400/day; wait, or pan to a smaller area. The dashboard polls only your visible map view. |
| `429 Too Many Requests` from OpenSky | You hit the daily quota. Resets at UTC midnight. |
| Drone counter shows `📡 Frames > 0` but `mgmt = 0` | Adapter is sniffing but not in monitor mode. Use a known-good adapter (§6b). |
| `Sniffer not running` even after clicking Start | You didn't pick an adapter from the dropdown. Pick one and click Start again. |
| `aisstream API key not configured` | Save the key in **Settings → API Keys** first (§7). |
| Buttons say "Start" while data is flowing | Hard-refresh browser (`Ctrl+Shift+R`) — cached JS. |
| Page renders blank / 404s for `/css/style.css` | Hard-refresh, then make sure you're hitting the URL the server prints (`http://127.0.0.1:8080`). |
