# Setup — SkyWatch (Python)

This covers what to install per OS. SkyWatch is pure Python, but the SDR pieces shell out to native binaries (`readsb`, `rtl_ais`, `rtl_fm`) and need an RTL-SDR driver and (on Windows) Npcap for drone-RID WiFi capture.

## 1. Python deps (all OSes)

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Python 3.10 or newer.

## 2. Linux (Debian / Ubuntu)

```bash
# Build chain + RTL-SDR + libpcap
sudo apt install -y build-essential cmake pkg-config \
                    librtlsdr-dev libpcap-dev rtl-sdr

# readsb (ADS-B)
git clone https://github.com/wiedehopf/readsb /tmp/readsb
cd /tmp/readsb && make RTLSDR=yes && sudo cp readsb /usr/local/bin/

# rtl_ais (AIS)
git clone https://github.com/dgiardini/rtl-ais /tmp/rtl-ais
cd /tmp/rtl-ais && make && sudo cp rtl_ais /usr/local/bin/

# Blacklist the kernel's DVB driver so RTL-SDR works for SDR
echo 'blacklist dvb_usb_rtl28xxu' | sudo tee /etc/modprobe.d/blacklist-rtl.conf

# Allow non-root access (replug the dongle after this)
sudo cp /etc/udev/rules.d/* 2>/dev/null
sudo udevadm control --reload-rules

# Drone Remote ID requires monitor-mode WiFi
sudo apt install -y iw wireless-tools
```

## 3. macOS

```bash
brew install librtlsdr libpcap

# readsb
git clone https://github.com/wiedehopf/readsb && cd readsb
make RTLSDR=yes && sudo cp readsb /usr/local/bin/

# rtl_ais
git clone https://github.com/dgiardini/rtl-ais && cd rtl-ais
make && sudo cp rtl_ais /usr/local/bin/
```

For drone-RID monitor mode on macOS, use a USB adapter (e.g. Alfa AWUS036ACH) — built-in WiFi doesn't reliably support monitor mode on recent macOS versions.

## 4. Windows

### RTL-SDR driver (required for ADS-B / AIS / NWR)

1. Download Zadig: https://zadig.akeo.ie/
2. Plug in your RTL-SDR dongle.
3. In Zadig: *Options → List All Devices*, pick **Bulk-In, Interface (Interface 0)**, target driver **WinUSB**, click **Replace Driver**.

### `readsb`, `rtl_ais`, `rtl_fm`

Download prebuilt Windows binaries:
- readsb: https://github.com/wiedehopf/readsb/releases (or build via WSL)
- rtl-sdr (provides `rtl_fm`): https://github.com/rtlsdrblog/rtl-sdr-blog/releases
- rtl-ais: https://github.com/dgiardini/rtl-ais (Windows build via MinGW or use WSL)

Place them somewhere on PATH (e.g. `C:\Tools\rtl-sdr\`) and add that to your system PATH.

### Drone Remote ID on Windows

You need both:

1. **A monitor-mode-capable USB WiFi adapter** — Alfa AWUS036ACH or AWUS036NHA are the usual choices.
2. **Npcap** with "Support raw 802.11 traffic (and monitor mode)" checked at install: https://npcap.com/

Then start SkyWatch with the adapter's interface name — usually something like `\Device\NPF_{GUID}`. List interfaces with:

```powershell
python -c "from scapy.all import get_if_list; print(get_if_list())"
```

## 5. Verify

```bash
python -m skywatch -version
python -m skywatch  # opens http://localhost:8080
```

If `readsb` / `rtl_ais` / `rtl_fm` aren't on PATH you can pass full paths:

```bash
python -m skywatch -readsb "C:\Tools\readsb.exe" -rtl-ais "C:\Tools\rtl_ais.exe"
```

## 6. Optional: import the aircraft database

This populates registration / type / operator on every ADS-B target. ~150 MB download from OpenSky, one-time. Either click **Import** in the dashboard's ADS-B panel or:

```bash
curl -X POST http://localhost:8080/api/aircraft/import
```
