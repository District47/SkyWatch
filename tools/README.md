# Bundled tools

`tools/win64/` ships **committed to the repo** so a fresh `git clone` produces a working install with no extra binary downloads. At startup, `skywatch/_bootstrap.py` auto-detects the right subfolder for the host OS and adds it to PATH + Windows DLL search before any subprocess or ctypes call runs.

## Folder layout

```
tools/
├── win64/            ← Windows x64 — committed (~47 MB)
├── python-win64/     ← embeddable Python — gitignored (per-machine; populated by scripts/setup-bundle.bat)
├── linux64/          ← Linux x86_64 — not yet populated
├── darwin-arm64/     ← Apple Silicon — not yet populated
└── darwin-x64/       ← Intel Mac — not yet populated
```

## What's in `tools/win64/`

| Component | Source | Purpose |
|---|---|---|
| `rtl_fm.exe`, `rtl_test.exe`, `rtl_sdr.exe`, `rtl_adsb.exe`, `rtl_biast.exe`, `rtl_eeprom.exe`, `rtl_power.exe`, `rtl_tcp.exe` | osmocom rtl-sdr / rtl-sdr-blog | RTL-SDR command-line drivers |
| `rtlsdr.dll`, `libusb-1.0.dll`, `pthreadVC2.dll`, `pthreadVC3.dll` | osmocom rtl-sdr / rtl-sdr-blog | runtime DLLs `pyrtlsdr` ctypes-loads |
| `AIS-catcher.exe` + `libcrypto-*.dll`, `libssl-*.dll`, `libzmq-*.dll`, `libpq.dll`, `soxr.dll`, `sqlite3.dll`, `airspy.dll`, `AIRSPYHF.dll`, `hackrf.dll`, `msvcr100.dll` | https://github.com/jvde-github/AIS-catcher | AIS RF decoder (162 MHz vessel tracking) |
| `multimon-ng.exe` + `cygwin1.dll` | https://github.com/cuppa-joe/multimon-ng (Windows build of EliasOenal/multimon-ng) | APRS RF demod (Bell-202 AFSK1200) |
| `vc_redist.x64.exe` | Microsoft | VC++ Redistributable installer; surfaced from Settings → Setup |
| `zadig.exe` | https://zadig.akeo.ie | RTL-SDR WinUSB driver swap (one-time per dongle) |
| `Licenses/` | upstream | GPL/MIT/etc. license texts that **must** ship alongside the binaries |
| `plugins/` | AIS-catcher | optional AIS-catcher data uploader configs |
| `*_static.lib`, `rtlsdr.exp`, `rtlsdr.lib` | upstream | linker artifacts (small; left in the upstream zip; harmless at runtime) |

## License compliance

All upstream binaries here are GPL / MIT / OSS licensed. Their license texts live in [tools/win64/Licenses/](win64/Licenses/) and **must stay there** in any redistribution. Source code for the GPL components is available at:

- librtlsdr / rtl_fm / rtl_test / etc. — https://github.com/rtlsdrblog/rtl-sdr-blog
- AIS-catcher — https://github.com/jvde-github/AIS-catcher
- multimon-ng — https://github.com/EliasOenal/multimon-ng (upstream, source) and https://github.com/cuppa-joe/multimon-ng (Windows binary fork)

If you ship a SkyWatch tester zip, those are your "written offer" links per GPLv3 §6. The README and SETUP.md already point at them.

## Updating a binary

If a new AIS-catcher / multimon-ng / rtl-sdr-blog release comes out:

1. Download the zip from upstream.
2. Extract over `tools/win64/` (overwriting the matching files).
3. Refresh the `Licenses/` subfolder if upstream changed it.
4. `git add tools/win64/ && git commit -m "deps: bump <component> to <version>"`.

Try not to add new files unless they're actually used at runtime. The folder is checked into git, so every byte sticks around forever.

## `tools/linux64/`, `tools/darwin-*/`

Not populated yet. System package managers (`apt`, `brew`) generally install these tools to `/usr/bin` already, so the launcher falls back to PATH on those platforms. If you want a fully portable Linux/macOS build, copy the equivalent binaries (`AIS-catcher`, `rtl_fm`, `multimon-ng`, `librtlsdr.so` / `librtlsdr.dylib`) into the matching subfolder.

## Verification

```bash
python -c "from skywatch._bootstrap import BUNDLED_TOOLS_DIR; print(BUNDLED_TOOLS_DIR)"
```

Should print `tools/win64/` (resolved to absolute path) on Windows. From there:

```bash
python -m skywatch -addr :8080
```

ADS-B (Aircraft tab → Device 0), AIS (Vessels tab → Device 1), and APRS RF (APRS tab → Settings → APRS RF → Device 0) all start without any further configuration — no `where.exe AIS-catcher` voodoo required.
