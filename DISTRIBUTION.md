# Distribution — Building a Tester Bundle

Maintainer-side notes for shipping SkyWatch zips to beta testers. Testers don't read this file; they read [QUICKSTART.md](QUICKSTART.md).

This is **Tier 1** — source-level distribution with bundled embeddable Python. Tester does not install Python or pip. Tier 2 (PyInstaller frozen build) is documented separately.

## One-time prep on this machine

1. **Populate `tools/win64/`** with all the native binaries (this is the same set the dev build uses).
   - From rtl-sdr-blog Windows release: `rtl_fm.exe`, `rtl_test.exe`, `librtlsdr.dll` (or `rtlsdr.dll`), `libusb-1.0.dll`, `pthreadVC2.dll`.
   - From AIS-catcher releases: `AIS-catcher.exe` + every DLL in its zip.
   - From cuppa-joe multimon-ng releases: `multimon-ng.exe` **AND** `cygwin1.dll`.
   - From Microsoft: `vc_redist.x64.exe`.
   - From Akeo: `zadig.exe`.

   Verify by listing the folder — it should match what's described in [tools/README.md](tools/README.md) plus the multimon-ng additions.

2. **Bundle the embeddable Python** by running:
   ```bat
   .\scripts\setup-bundle.bat
   ```
   This downloads the Windows embeddable Python zip, extracts it into `tools\python-win64\`, bootstraps pip, and pip-installs everything in `requirements.txt`. End state: `tools\python-win64\python.exe -m skywatch -version` works without any system Python.

   Override the version if needed:
   ```bat
   .\scripts\setup-bundle.bat 3.13.7
   ```

   Default is `3.13.7` (most stable mainstream when this script was written; 3.14 may not yet have wheels for every C-extension package on PyPI). If you change the version, also update [QUICKSTART.md](QUICKSTART.md) if you mention it there.

## Per-release prep

Each time you cut a beta drop:

### 1. Smoke-test on this machine

```bat
.\start.bat -version
```

Should print `skywatch <version>` without touching system Python. If it fails, the bundle is broken — fix before zipping.

Then run the full app once and click through:

- Settings → Aircraft → Online (OpenSky) → Start. Confirm aircraft appear on the map.
- Settings → APRS → APRS-IS → Start with a placeholder callsign. Confirm `INFO skywatch.aprs.is` lines appear in the console.
- (If a dongle is plugged in) Settings → Aircraft → Device 0 → Start. Confirm decoder spawns without error.

### 2. Clean up developer cruft before zipping

These directories should NOT ship to testers:

```bat
rmdir /s /q .venv
rmdir /s /q __pycache__
del /s /q *.pyc
rmdir /s /q .pytest_cache 2>nul
rmdir /s /q logs 2>nul
del data\api_keys.json 2>nul
```

`data\api_keys.json` is gitignored but may exist locally. `.venv` is the developer's venv — testers use the bundled `tools\python-win64\` instead.

Keep:
- `tools\win64\` — RF binaries.
- `tools\python-win64\` — bundled Python with deps installed.
- `data\aircraft.json` if you want testers to start with a populated aircraft DB (huge file — usually skip).

### 3. Stamp the version

Edit [skywatch/__init__.py](skywatch/__init__.py) and bump `__version__`. Use `<base-version>-betaN` so testers can tell drops apart in their logs.

### 4. Zip the project

```powershell
$date = Get-Date -Format yyyyMMdd
Compress-Archive -Path "C:\Users\Owner\projects\SkyWatch-py\*" `
                 -DestinationPath "C:\Users\Owner\Desktop\SkyWatch-beta-$date.zip" `
                 -CompressionLevel Optimal
```

Expected size: 100–250 MB depending on whether numpy/scipy are included and which RF binaries you bundle. The bulk is `tools\python-win64\Lib\site-packages\` (numpy + scipy MKL DLLs) and `tools\win64\` (AIS-catcher's plugins folder).

### 5. Verify the zip on a clean Windows VM (highly recommended)

The whole point of Tier 1 is that testers don't need a developer environment, so test that. Spin up a fresh Windows VM with no Python installed:

1. Copy the zip in.
2. Right-click → Extract All.
3. Double-click `start.bat`.
4. Open `http://localhost:8080`.

If anything in this flow requires extra steps you didn't document, fix QUICKSTART.md before shipping.

## What testers receive

A single zip → a `start.bat` they double-click → a working dashboard. No Python install, no `pip install`, no driver headaches except Zadig (one-time, documented in QUICKSTART.md §2).

The launcher detects the bundled Python at `tools\python-win64\python.exe` and skips all the venv / pip-install logic. If the bundled Python is missing (e.g. the tester deleted it), it falls back to system Python — useful for developers running the same `start.bat` against their dev environment.

## Things that will not work for testers without extra setup

Cover these explicitly in the email/Slack message you send with the zip:

| Feature | What's missing | How to add |
|---|---|---|
| RTL-SDR-driven modules | Zadig WinUSB driver replacement | QUICKSTART.md §2 |
| Drone Remote ID — WiFi monitor mode | Npcap install + a chipset that supports monitor mode | SETUP.md §6 (skip unless needed) |
| Online vessel feed | aisstream.io API key | Settings → API Keys |
| APRS-IS transmit (beacons / messages) | A real ham callsign + APRS-IS passcode | They probably already have one if they care |

## Known limits of Tier 1

- **Updates are full re-downloads.** No diff/auto-update yet. Acceptable for beta cadence (drops every week or two).
- **Tester logs are local only.** No automatic upload — they email/paste them back. Add a `Settings → Send Logs` button in a later iteration if it gets painful.
- **Windows SmartScreen.** Bundled binaries (`AIS-catcher.exe`, `rtl_fm.exe`, `multimon-ng.exe`, `start.bat`) are unsigned. Testers will see "Windows protected your PC" → "More info → Run anyway." Document this. Code-signing certs are ~$80/yr if you decide it's worth it.
- **Embeddable Python is not 100% feature-equivalent** to a normal install. Tkinter, IDLE, and a few stdlib helpers are absent. SkyWatch doesn't use any of them, but watch out if you add new deps that pull them in.

## Going from Tier 1 to Tier 2 later

Once Tier 1 is solid, freezing it with PyInstaller is mostly mechanical: write a `skywatch.spec` that includes `tools/win64/` as data, list `pyrtlsdr` / `scapy` / `numpy` / `scipy` in `hiddenimports`, and ship `--onedir` output instead of the zip. The work is debugging PyInstaller's discovery quirks — not redesigning the app.
