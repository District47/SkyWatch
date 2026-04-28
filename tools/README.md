# Bundled tools

Drop platform-specific binaries here so SkyWatch ships as a single folder. At startup, `skywatch/_bootstrap.py` auto-detects the right subfolder for the host OS and adds it to PATH + Windows DLL search before any subprocess or ctypes call runs.

## Folder layout

```
tools/
├── win64/        ← Windows x64
├── linux64/      ← Linux x86_64
├── darwin-arm64/ ← Apple Silicon
└── darwin-x64/   ← Intel Mac
```

Only the folder for your target OS needs to be populated.

## What goes in each folder

### `tools/win64/` (most common case for distribution)

From rtl-sdr-blog V4 (https://github.com/rtlsdrblog/rtl-sdr-blog/releases — `Release.zip`, take the `x64` subfolder):

- `librtlsdr.dll` (or `rtlsdr.dll` on older builds — pyrtlsdr accepts either)
- `libusb-1.0.dll`
- `pthreadVC2.dll`
- `rtl_fm.exe` ← used by NWR Weather Radio
- `rtl_test.exe` (optional, useful for verification)

From AIS-catcher (https://github.com/jvde-github/AIS-catcher/releases — `AIS-catcher.x64.zip`):

- `AIS-catcher.exe`
- All accompanying `.dll`s in the zip (libcrypto, libssl, libzmq, libusb, soxr, sqlite3, etc.)
- `Licenses/` and `plugins/` folders if you want them

For ADS-B, you don't need anything here — SkyWatch's pure-Python decoder uses pyrtlsdr directly. If you'd rather use `readsb`, drop `readsb.exe` in this folder too.

### `tools/linux64/`, `tools/darwin-*/`

System package managers (`apt`, `brew`) generally install these to `/usr/bin` already, so you usually don't need to bundle. If you want a fully portable Linux build, copy the same set of binaries (`AIS-catcher`, `rtl_fm`, `librtlsdr.so`).

## Why this isn't committed by default

`tools/*/` is in `.gitignore` because:

1. The binaries are large (~30–50 MB combined) and inflate `git clone` time.
2. Their licenses (GPL for librtlsdr / readsb, MIT for AIS-catcher) require redistribution under matching terms — fine, but worth being intentional about.
3. Your shipped build may pin specific versions different from what someone else wants.

If **you** want to commit them for your own distribution, just delete the relevant lines from `.gitignore` and `git add tools/win64/`.

## Verification

After populating:

```bash
python -c "from skywatch._bootstrap import BUNDLED_TOOLS_DIR; print(BUNDLED_TOOLS_DIR)"
```

Should print the absolute path you populated. From there:

```bash
python -m skywatch -addr :8080
```

ADS-B (Aircraft tab → Device 0) and AIS (Vessels tab → Device 1) will start without any further configuration — no `where.exe AIS-catcher` voodoo required.
