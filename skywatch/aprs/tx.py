"""APRS transmit helpers: passcode, position formatting, beacon/message build.

The Go version uses `github.com/ebarkie/aprs` which implements the APRS-IS
passcode algorithm. Same algorithm, replicated below.
"""
from __future__ import annotations


def compute_passcode(callsign: str) -> int:
    """APRS-IS passcode for a callsign (no SSID). Returns 0..32767."""
    cs = callsign.upper().split("-")[0]
    code = 0x73E2
    i = 0
    while i + 1 < len(cs):
        code ^= (ord(cs[i]) << 8) | ord(cs[i + 1])
        i += 2
    if i < len(cs):
        code ^= ord(cs[i]) << 8
    return code & 0x7FFF


def format_callsign(callsign: str, ssid: int) -> str:
    """`W5ABC-9` style. SSID 0 = no suffix."""
    cs = callsign.upper().strip()
    if ssid and 0 < ssid <= 15:
        return f"{cs}-{ssid}"
    return cs


def _format_lat(lat: float) -> str:
    h = "N" if lat >= 0 else "S"
    lat = abs(lat)
    deg = int(lat)
    minutes = (lat - deg) * 60.0
    return f"{deg:02d}{minutes:05.2f}{h}"


def _format_lon(lon: float) -> str:
    h = "E" if lon >= 0 else "W"
    lon = abs(lon)
    deg = int(lon)
    minutes = (lon - deg) * 60.0
    return f"{deg:03d}{minutes:05.2f}{h}"


def build_position_beacon(*, callsign: str, ssid: int, symbol: str, lat: float, lon: float,
                          altitude_ft: int = 0, comment: str = "",
                          path: str = "TCPIP*", destination: str = "APSKY",
                          messaging: bool = True) -> str:
    """Build a TNC2-formatted APRS position frame ready for the IS gateway."""
    src = format_callsign(callsign, ssid)
    sym_table = (symbol[0:1] or "/")
    sym_code = (symbol[1:2] or ">")
    dti = "=" if messaging else "!"
    body = f"{dti}{_format_lat(lat)}{sym_table}{_format_lon(lon)}{sym_code}"
    if altitude_ft and altitude_ft != 0:
        body += f"/A={altitude_ft:06d}"
    if comment:
        body += comment
    return f"{src}>{destination},{path}:{body}"


def build_message(*, from_callsign: str, ssid: int, to_callsign: str, text: str,
                  msg_id: str = "", path: str = "TCPIP*", destination: str = "APSKY") -> str:
    src = format_callsign(from_callsign, ssid)
    target = to_callsign.upper().ljust(9)
    info = f":{target}:{text}"
    if msg_id:
        info += f"{{{msg_id}"
    return f"{src}>{destination},{path}:{info}"


def build_status(*, callsign: str, ssid: int, status: str,
                 path: str = "TCPIP*", destination: str = "APSKY") -> str:
    src = format_callsign(callsign, ssid)
    return f"{src}>{destination},{path}:>{status}"
