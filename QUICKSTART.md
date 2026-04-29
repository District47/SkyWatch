# SkyWatch — Quick Start (Beta Testers)

Welcome. This is the short version of SETUP.md aimed at getting you up and running in **under 10 minutes**, including the RTL-SDR driver step.

You don't need Python, pip, or any developer tooling. Everything is bundled.

---

## What you got

A zip file (something like `SkyWatch-beta-YYYYMMDD.zip`) containing:

- A `start.bat` launcher (Windows) — double-click to run.
- A bundled Python interpreter — no separate install needed.
- A bundled `tools/win64/` folder with **everything pre-installed**: the RTL-SDR drivers (`rtlsdr.dll`, `libusb-1.0.dll`), the command-line tools (`rtl_fm`, `rtl_test`), `AIS-catcher` for ship tracking, `multimon-ng` + `cygwin1.dll` for off-air APRS, the VC++ Redistributable installer, and `Zadig` for the one-time driver swap.
- The dashboard, parsers, and decoders.

> [!NOTE]
> **You shouldn't have to download anything else.** If `start.bat` complains a file is missing, that's a packaging bug — please send the error along with the log file from `logs\` and we'll fix it.

---

## What you need

| Need | Why | Where |
|---|---|---|
| Windows 10 or 11, 64-bit | What this beta is built for | Already installed |
| About 500 MB free disk space | For the unzipped folder | — |
| An RTL-SDR USB dongle (optional) | For ADS-B / AIS / NOAA / APRS RF reception | RTL-SDR Blog V3 or V4 recommended ($35 from rtl-sdr.com or Amazon) |
| An antenna for whatever bands you want to monitor (optional) | Aircraft = ~1090 MHz, ships = ~162 MHz, APRS = 144.39 MHz, NOAA WX = 162.4 MHz | Stock dipole or a wire at the right length |
| A web browser | The dashboard is a webpage at `http://localhost:8080` | Already installed |

If you skip the RTL-SDR you can still run SkyWatch — you'll get **online-only feeds**: aircraft from OpenSky and (with an API key) ships from aisstream.io. APRS-IS internet feed also works without hardware.

---

## First-time setup (≤10 minutes)

### 1. Unzip

Right-click the zip → **Extract All** → pick a folder you control (e.g. `C:\SkyWatch\`). Don't extract into Program Files.

### 2. (Only if you have an RTL-SDR) Install the WinUSB driver with Zadig

This is a one-time step per dongle. Skip if you don't have a dongle.

1. Plug the dongle in.
2. In the unzipped folder, go to `tools\win64\` and **double-click `zadig.exe`**.
3. In Zadig: **Options → List All Devices**.
4. From the dropdown, pick **Bulk-In, Interface (Interface 0)** — its description usually starts with `RTL2838` or `RTL2832`.
5. Make sure the target driver on the right says **WinUSB**.
6. Click **Replace Driver**. Wait for the success message.
7. Close Zadig.

If you have multiple dongles, repeat for each one.

> **⚠️ Don't skip this** — without WinUSB, SkyWatch can't talk to the dongle and any "Start" button that uses RTL-SDR will fail.

### 3. Run SkyWatch

Double-click **`start.bat`** in the unzipped folder.

A console window opens, prints some setup lines, then says:

```
============================================================
 Launching SkyWatch.  Open http://localhost:8080
 (Ctrl+C in this window stops the server.)
============================================================
```

Open **http://localhost:8080** in your browser. You'll see the map dashboard.

> **Leave the console window open** while you use the app. Closing it stops the server.

### 4. Try a feature

Click the gear icon (top-right) to open **Settings**. Each module has a **Start** button. Easy ones to try first:

| Feature | What you need | Where to click |
|---|---|---|
| Aircraft (OpenSky internet feed) | Nothing — works on any internet connection | Settings → Aircraft → **Online (OpenSky)** → Start |
| Aircraft (your dongle) | RTL-SDR + ADS-B antenna | Settings → Aircraft → pick a Device → Start |
| Vessels (your dongle) | RTL-SDR + 162 MHz antenna | Settings → Vessels → pick a Device → Start |
| APRS (internet feed) | Nothing | Settings → APRS → **APRS-IS** → Start |
| APRS (your dongle) | RTL-SDR + 2 m antenna | Settings → APRS → **APRS RF** → pick a Device → Start |
| NOAA Weather Radio | RTL-SDR + 162 MHz antenna | NOAA tab → click a transmitter → Listen |

Watch the map fill up. Use the tabs on the right to filter (All / Aircraft / Vessels / Drones / APRS / NOAA).

---

## How to report a problem

When something doesn't work, send back **two things**:

1. **The console window text.** Right-click the console title bar → **Edit → Select All → Copy** → paste into the bug report.
2. **The latest log file.** Inside the unzipped folder there's a `logs\` directory. Send the most recent `skywatch-YYYYMMDD-HHMMSS.log` file.

Add a one-line description: what you clicked, what you expected, what happened.

---

## Common gotchas

| Symptom | Fix |
|---|---|
| `start.bat` flashes and disappears | Open `cmd.exe`, `cd` into the unzipped folder, run `start.bat` from there — you'll see the actual error. |
| Browser says "can't connect to localhost:8080" | The console window probably crashed. Check the log in `logs\`. |
| RTL-SDR Start button errors with "device not found" | You skipped the Zadig step (§2). Run Zadig and replace the driver. |
| RTL-SDR Start button errors with `RTL-SDR #N is already in use` | Each dongle can only feed one module at a time. Stop the other module, or plug in a second dongle. |
| ADS-B / AIS / APRS stays empty for 10+ minutes | Almost always antenna or location. Try the OpenSky online feed first to verify the dashboard is alive, then troubleshoot RF. |
| `WARNING: missing VC++ Redistributable` | Open **Settings → Setup**; there's an Install button for it. |
| Windows SmartScreen blocks an installer | Click **More info → Run anyway**. The bundled binaries aren't signed. |

---

## What changes between beta drops

When a new zip arrives, just **delete the old folder** and unzip the new one in its place. Your settings live in `data/` — copy that folder over from the old install if you want to keep your saved API keys / alert zones / callsign.

---

## What this build CAN'T do (yet)

- **APRS UV-Pro Bluetooth TNC** — button is there, decoder is stubbed.
- **Drone Remote ID over WiFi** — works, but requires Npcap (separate install) and a specific USB WiFi adapter (most laptops' built-in WiFi cards refuse). The Bluetooth-LE drone path works out of the box. See SETUP.md §6 if you want to try the WiFi path.
- **APT image geometric correction** — captures look wavy. Cosmetic only.

Everything else in the dashboard should work. If it doesn't, that's the feedback we want.

Thanks for testing.
